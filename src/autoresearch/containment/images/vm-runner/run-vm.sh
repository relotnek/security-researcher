#!/bin/sh
# Boot a guest VM bridged at layer 2 onto this container's only network
# interface - the isolated segment. The container itself is just the VM's
# chassis: the guest gets its own MAC and address on the segment.
#
# Configuration (environment):
#   VM_ARCH      qemu-system-<arch> to use            (default x86_64)
#   VM_MACHINE   -M value                             (optional)
#   VM_MEMORY    guest RAM in MiB                     (default 256)
#   VM_KERNEL    kernel image path                    (optional)
#   VM_INITRD    initrd path                          (optional)
#   VM_APPEND    kernel command line                  (optional)
#   VM_DISK_SIZE size of /vm/disk.qcow2, created on first boot (optional)
#   VM_NIC       NIC model                            (default virtio-net-pci)
#   VM_MAC       guest MAC address                    (required)
#   VM_EXTRA     extra qemu arguments                 (optional)
set -eu

mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200

ADDR=$(ip -4 -o addr show dev eth0 | awk '{print $4}')
ip link add br0 type bridge
ip tuntap add dev tap0 mode tap
ip addr flush dev eth0
ip link set eth0 master br0
ip link set tap0 master br0
ip link set br0 up
ip link set tap0 up
ip addr add "$ADDR" dev br0

set -- -display none -serial stdio -no-reboot -m "${VM_MEMORY:-256}" \
    -monitor unix:/run/qemu-monitor.sock,server=on,wait=off \
    -netdev tap,id=seg0,ifname=tap0,script=no,downscript=no \
    -device "${VM_NIC:-virtio-net-pci},netdev=seg0,mac=${VM_MAC}"
[ -n "${VM_MACHINE:-}" ] && set -- "$@" -M "$VM_MACHINE"
[ -n "${VM_KERNEL:-}" ] && set -- "$@" -kernel "$VM_KERNEL"
[ -n "${VM_INITRD:-}" ] && set -- "$@" -initrd "$VM_INITRD"
[ -n "${VM_APPEND:-}" ] && set -- "$@" -append "$VM_APPEND"
if [ -n "${VM_DISK_SIZE:-}" ]; then
    [ -f /vm/disk.qcow2 ] || qemu-img create -q -f qcow2 /vm/disk.qcow2 "$VM_DISK_SIZE"
fi
if [ -f /vm/disk.qcow2 ]; then
    set -- "$@" -drive file=/vm/disk.qcow2,format=qcow2,if=virtio
fi
# shellcheck disable=SC2086
exec "qemu-system-${VM_ARCH:-x86_64}" "$@" ${VM_EXTRA:-}
