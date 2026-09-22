#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
USB_VID=''
USB_PID=''
ACCESS_GROUP=''
DRY_RUN=0
usage() {
    cat <<'HELP'
用法：sudo ./scripts/install_udev_rules.sh [--vid 1234 --pid abcd] [--group GROUP]
      ./scripts/install_udev_rules.sh --dry-run [同上参数]
安装 CMSIS-DAP USB/hidraw 规则，默认授权当前本地桌面会话。
--vid/--pid  为产品名不含 CMSIS-DAP 的探针追加精确 USB ID 规则。
--group     同时授权已有 Unix 组，适用于 SSH 或无 logind 的系统。
--dry-run   输出即将安装的规则，不修改系统。
脚本不执行 sudo，不创建用户组；安装后请拔插探针。
HELP
}
while [[ $# -gt 0 ]]; do
    case "$1" in
        --vid|--pid|--group)
            if [[ $# -lt 2 ]]; then echo "[错误] $1 缺少参数。" >&2; exit 2; fi
            case "$1" in
                --vid) USB_VID="${2,,}" ;;
                --pid) USB_PID="${2,,}" ;;
                --group) ACCESS_GROUP="$2" ;;
            esac
            shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [[ "$(uname -s)" != Linux ]]; then echo '[错误] udev 规则仅适用于 Linux。' >&2; exit 1; fi
if [[ -n "$USB_VID$USB_PID" ]] && { [[ ! "$USB_VID" =~ ^[0-9a-f]{4}$ ]] || [[ ! "$USB_PID" =~ ^[0-9a-f]{4}$ ]]; }; then
    echo '[错误] --vid 和 --pid 必须同时提供四位十六进制值，如 --vid 0d28 --pid 0204。' >&2
    exit 2
fi
if [[ -n "$ACCESS_GROUP" ]]; then
    if [[ ! "$ACCESS_GROUP" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]] || ! getent group "$ACCESS_GROUP" >/dev/null; then
        echo '[错误] --group 必须指定已存在的 Unix 组；请先由管理员创建该组。' >&2
        exit 2
    fi
fi
if [[ $DRY_RUN -eq 0 ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo '[错误] 安装到 /etc/udev/rules.d 需要管理员权限；请手动使用 sudo 执行此脚本，或 --dry-run 预览。' >&2
        exit 1
    fi
    if ! command -v udevadm >/dev/null 2>&1; then echo '[错误] 未安装 udevadm。' >&2; exit 1; fi
fi
RULES_TMP="$(mktemp)"
trap 'rm -f -- "$RULES_TMP"' EXIT
cat "$APP_DIR/udev/60-dap-downloader.rules" > "$RULES_TMP"
if [[ -n "$USB_VID" ]]; then
    cat >> "$RULES_TMP" <<RULES

# Additional probe explicitly selected by VID/PID.
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="$USB_VID", ATTR{idProduct}=="$USB_PID", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="$USB_VID", ATTRS{idProduct}=="$USB_PID", MODE="0660", TAG+="uaccess"
RULES
fi
if [[ -n "$ACCESS_GROUP" ]]; then
    sed -i "s/MODE=\"0660\"/GROUP=\"$ACCESS_GROUP\", MODE=\"0660\"/g" "$RULES_TMP"
fi
if [[ $DRY_RUN -eq 1 ]]; then
    cat "$RULES_TMP"
    exit 0
fi
install -m 0644 "$RULES_TMP" /etc/udev/rules.d/60-dap-downloader.rules
udevadm control --reload-rules
printf '规则已安装。请拔插探针后以普通用户重新检测。\n'
if [[ -n "$ACCESS_GROUP" ]]; then
    printf '同时授权的组：%s。新增组成员需要注销并重新登录后生效。\n' "$ACCESS_GROUP"
fi
