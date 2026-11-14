# Test fixture: a tiny Linux guest that boots, joins the segment, and reports
# what it can reach on its serial console. Stands in for an emulated firmware.
ARG RUNNER
FROM alpine:3.21 AS build
RUN apk add --no-cache linux-virt busybox-static kmod cpio gzip zstd
COPY init /initramfs/init
RUN set -eux; \
    KV=$(ls /lib/modules); \
    mkdir -p /initramfs/bin /initramfs/mods /initramfs/proc /initramfs/sys /initramfs/dev; \
    cp /bin/busybox.static /initramfs/bin/busybox; \
    chmod +x /initramfs/init; \
    for m in virtio_pci virtio_net virtio_blk; do modprobe -S "$KV" --show-depends "$m"; done \
        | awk '$1=="insmod"{print $2}' | awk '!seen[$0]++' > /tmp/mods; \
    : > /initramfs/mods/order; \
    while read -r f; do \
        b=$(basename "$f"); \
        case "$f" in \
            *.gz)  b=${b%.gz};  gunzip -c "$f" > "/initramfs/mods/$b" ;; \
            *.zst) b=${b%.zst}; zstd -dc "$f" > "/initramfs/mods/$b" ;; \
            *)     cp "$f" "/initramfs/mods/$b" ;; \
        esac; \
        echo "$b" >> /initramfs/mods/order; \
    done < /tmp/mods; \
    cat /initramfs/mods/order; \
    (cd /initramfs && find . | cpio -o -H newc | gzip) > /initramfs.gz; \
    cp /boot/vmlinuz-virt /vmlinuz

FROM ${RUNNER}
COPY --from=build /vmlinuz /vm/vmlinuz
COPY --from=build /initramfs.gz /vm/initramfs.gz
