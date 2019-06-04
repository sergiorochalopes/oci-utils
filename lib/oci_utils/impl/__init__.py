#
# Copyright (c) 2018, 2019 Oracle and/or its affiliates. All rights reserved.
# Licensed under the Universal Permissive License v 1.0 as shown
# at http://oss.oracle.com/licenses/upl.
#

import io
import logging
import os
import os.path
import sys
import threading
from ConfigParser import ConfigParser
from datetime import datetime, timedelta
from logging.handlers import SysLogHandler
from time import sleep

from ..exceptions import OCISDKError

__all__ = ['lock_thread', 'release_thread', 'read_config', 'SUDO_CMD']

SUDO_CMD = '/bin/sudo'
VIRSH_CMD = '/usr/bin/virsh'
IP_CMD = '/usr/sbin/ip'
BRIDGE_CMD = '/sbin/bridge'
PARTED_CMD = '/sbin/parted'
MK_XFS_CMD = '/sbin/mkfs.xfs'


def print_error(msg, *args):
    """
    Write a message to the standard error.

    Parameters
    ----------
    msg: str
        The message.
    args: list
        The format string.

    Returns
    -------
        No return value.
    """
    sys.stderr.write(msg.format(*args))
    sys.stderr.write('\n')


def print_choices(header, choices, sep="\n  "):
    """
    Display a list of options.

    Parameters
    ----------
    header: str
        The header.
    choices: list
        The list of options.
    sep: str
        The optinal separator.

    Returns
    -------
        No return value.
    """
    print_error("{}{}{}", header, sep, sep.join(choices))


_oci_utils_thread_lock = threading.Lock()
_oci_utils_thread_lock_owner = None
_oci_utils_thread_lock_owner_l = threading.Lock()


def lock_thread(timeout=30):
    """
    Timed locking; set a threading lock with timeout.

    Parameters
    ----------
    timeout: int
        Timeout in second to acquire the lock, default is 30sec.

    Returns
    -------
        No return valiue.

    Raises
    ------
        OCISDKError
            If timeout occured

    """
    global _oci_utils_thread_lock
    global _oci_utils_thread_lock_owner, _oci_utils_thread_lock_owner_l

    # RE-ENTRANT not supported. check that the lock is free
    # or not already acquired
    _re_entrance_detected = False
    _oci_utils_thread_lock_owner_l.acquire(True)
    if _oci_utils_thread_lock_owner == threading.currentThread():
        _re_entrance_detected = True
    _oci_utils_thread_lock_owner_l.release()

    assert (not _re_entrance_detected), 'trying to acquire a lock twice !'

    if timeout > 0:
        max_time = datetime.now() + timedelta(seconds=timeout)
        while True:
            # non-blocking
            if _oci_utils_thread_lock.acquire(False):
                _oci_utils_thread_lock_owner_l.acquire(True)
                _oci_utils_thread_lock_owner = threading.currentThread()
                _oci_utils_thread_lock_owner_l.release()
                break
            if max_time < datetime.now():
                raise OCISDKError("Timed out waiting for API thread lock")
            else:
                sleep(0.1)
    else:
        # blocking
        _oci_utils_thread_lock.acquire(True)
        _oci_utils_thread_lock_owner_l.acquire(True)
        _oci_utils_thread_lock_owner = threading.currentThread()
        _oci_utils_thread_lock_owner_l.release()


def release_thread():
    """
    Release the thread lock.

    Returns
    -------
        No return value.

    Raises
    ------
       ThreadError
           If lock not currently locked.
    """

    global _oci_utils_thread_lock
    global _oci_utils_thread_lock_owner_l
    global _oci_utils_thread_lock_owner

    _safe_unlock = True

    _oci_utils_thread_lock_owner_l.acquire(True)
    if _oci_utils_thread_lock_owner != threading.currentThread():
        _safe_unlock = False
    _oci_utils_thread_lock_owner = None
    _oci_utils_thread_lock_owner_l.release()

    assert _safe_unlock, 'trying to relase a unlocked lock'

    _oci_utils_thread_lock.release()


# oci-utils configuration defaults
__oci_utils_defaults = """
[auth]
auth_method = auto
oci_sdk_user = opc
[iscsi]
enabled = true
scan_interval = 60
max_volumes = 8
auto_resize = true
auto_detach = true
detach_retry = 5
[vnic]
enabled = true
scan_interval = 60
vf_net = false
[public_ip]
enabled = true
refresh_interval = 600
"""

# oci-utils config file
__oci_utils_conf_d = "/etc/oci-utils.conf.d"
oci_utils_config = None


def read_config():
    """
    Read the oci-utils config files; read all files present in
    /etc/oci-utils.conf.d in order and populate a configParser instance.
    If no configuration file is found the default values are used. See
    __oci_utils_defaults.

    Returns
    -------
        [ConfigParser]
            The oci_utils configuration.
    """
    global oci_utils_config
    if oci_utils_config is not None:
        return oci_utils_config

    oci_utils_config = ConfigParser()
    try:
        oci_utils_config.readfp(io.BytesIO(__oci_utils_defaults))
    except Exception:
        raise

    if not os.path.exists(__oci_utils_conf_d):
        return oci_utils_config

    conffiles = [os.path.join(__oci_utils_conf_d, f)
                 for f in os.listdir(__oci_utils_conf_d)
                 if os.path.isfile(os.path.join(__oci_utils_conf_d, f))]
    oci_utils_config.read(conffiles)
    return oci_utils_config


def setup_logging():
    """
    General function to setup logger
    """

    if os.environ.get('_OCI_UTILS_SYSLOG'):
        handler = SysLogHandler(address='/dev/log',
                                facility=SysLogHandler.LOG_DAEMON)
    else:
        handler = logging.StreamHandler(stream=sys.stderr)

    logging.getLogger('oci-utils').setLevel(logging.WARNING)

    if os.environ.get('_OCI_UTILS_DEBUG'):
        logging.getLogger('oci-utils').setLevel(logging.DEBUG)
        handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(name)s - %(levelname)s(:%(lineno)s) - %(message)s')
    handler.setFormatter(formatter)

    logging.getLogger('oci-utils').addHandler(handler)