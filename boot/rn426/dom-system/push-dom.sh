#!/bin/sh
# From the workstation: send the DOM system image to the NAS (host "ng") and write it to the DOM.
# The NAS must run the Tenerix pendrive system or Alpine Live with sshd. One YubiKey touch.
set -eu
cd "$(dirname "$0")/../../.."
tar -C artifacts/dom-system -cf - tenerix-rn426-dom-system.img tenerix-rn426-dom-system.img.sha256 \
    -C ../../boot/rn426/dom-system write-dom.sh \
  | ssh ng 'mkdir -p /run/tw && tar -x -C /run/tw && echo TAK | sh /run/tw/write-dom.sh'
