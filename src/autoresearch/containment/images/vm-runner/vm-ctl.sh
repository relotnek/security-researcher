#!/bin/sh
# Send one command to the guest's QEMU monitor and report the VM status.
#   vm-ctl stop   pause the guest and flush its disks (a consistent disk image)
#   vm-ctl cont   resume the guest
set -eu
(echo "$1"; echo "info status"; sleep 1) | socat - UNIX-CONNECT:/run/qemu-monitor.sock
