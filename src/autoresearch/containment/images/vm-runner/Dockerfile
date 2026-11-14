FROM alpine:3.21
RUN apk add --no-cache qemu-system-x86_64 qemu-system-arm qemu-system-aarch64 \
        qemu-system-mips qemu-system-mipsel qemu-img iproute2 socat
COPY run-vm.sh /usr/local/bin/run-vm
COPY vm-ctl.sh /usr/local/bin/vm-ctl
RUN chmod +x /usr/local/bin/run-vm /usr/local/bin/vm-ctl && mkdir -p /vm
ENTRYPOINT ["/usr/local/bin/run-vm"]
