"""Minimal standalone test for TUCAM_Buf_WaitForFrame.
Run directly to exercise the driver without the full interface stack.

Example:
    python tools/test_tucam_waitforframe.py --frames 5 --exposure 0.5 --timeout 5000 --roi 0 1220 2048 148

This will:
  1. Init API
  2. Open first camera
  3. (Optionally) set ROI & exposure
  4. Allocate buffer & start capture
  5. Repeatedly call TUCAM_Buf_WaitForFrame and report frame stats
  6. Clean up resources
"""
import argparse
import ctypes
import logging
import os
import sys
import time
from ctypes import pointer, byref, cast, POINTER

import numpy as np

from TUCam import *  # noqa

# ---------------------------------------------------------------------------
# Override restype so ctypes does NOT auto-convert to Enum (which was raising
# ValueError for codes with the high bit set due to sign/unsigned mismatch)
# We will manually map to TUCAMRET after masking to 32-bit unsigned.
# ---------------------------------------------------------------------------
try:  # protect against future SDK changes
    TUCAM_Buf_WaitForFrame.restype = ctypes.c_int32  # type: ignore[attr-defined]
except Exception:
    pass

LOG = logging.getLogger("tucam_waitforframe_test")


def _mask32(code: int) -> int:
    return ctypes.c_uint32(code).value  # normalize signed/unsigned


def decode_ret(code: int) -> str:
    unsigned = _mask32(code)
    try:
        return f"{TUCAMRET(unsigned).name} (0x{unsigned:08X})"
    except Exception:
        return f"UNKNOWN_RET (0x{unsigned:08X} raw_signed={code})"


def is_success(code: int) -> bool:
    unsigned = _mask32(code)
    return unsigned == TUCAMRET.TUCAMRET_SUCCESS.value


def check(ret, msg, fatal=True):
    if not is_success(ret):
        LOG.error(f"{msg} -> {decode_ret(ret)}")
        if fatal:
            raise SystemExit(2)
        return False
    else:
        LOG.debug(f"{msg} -> OK")
        return True


def dump_frame_struct(frame: 'TUCAM_FRAME', prefix: str = "FrameStruct"):
    try:
        LOG.debug(
            f"{prefix}: header={frame.usHeader} width={frame.usWidth} height={frame.usHeight} ch={frame.ucChannels} elemBytes={frame.ucElemBytes} uiImgSize={frame.uiImgSize} pBuffer=0x{int(ctypes.addressof(ctypes.c_char.from_address(ctypes.addressof(frame) + 0))):X}"  # noqa: E501
        )
    except Exception:
        LOG.debug(f"{prefix}: (failed to format)")


def set_exposure(hcam, seconds: float):
    # Disable auto exposure first
    TUCAM_Capa_SetValue(hcam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, 0)
    ms_val = float(seconds) * 1000.0
    ret = TUCAM_Prop_SetValue(hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, ms_val, 0)
    check(ret, f"Set exposure {seconds}s ({ms_val} ms)")
    val = ctypes.c_double()
    if TUCAM_Prop_GetValue(hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, byref(val), 0) == TUCAMRET.TUCAMRET_SUCCESS:
        LOG.info(f"Exposure now: {val.value/1000.0:.3f} s (raw {val.value})")


def set_roi(hcam, roi_tuple):
    (h_off, v_off, width, height) = roi_tuple
    roi = TUCAM_ROI_ATTR()
    roi.bEnable = 1
    roi.nHOffset = int(h_off)
    roi.nVOffset = int(v_off)
    roi.nWidth = int(width)
    roi.nHeight = int(height)
    ret = TUCAM_Cap_SetROI(hcam, roi)
    check(ret, f"Set ROI {roi_tuple}")


def frame_to_numpy(frame: TUCAM_FRAME):
    if not frame.pBuffer:
        LOG.error("Frame pBuffer is NULL")
        return None
    total_size = frame.usHeader + frame.uiImgSize
    raw = np.ctypeslib.as_array(cast(frame.pBuffer, POINTER(ctypes.c_ubyte)), shape=(total_size,))
    payload = raw[frame.usHeader: frame.usHeader + frame.uiImgSize]
    # Infer dtype
    if frame.ucElemBytes == 2:
        dtype = np.uint16
    elif frame.ucElemBytes == 1:
        dtype = np.uint8
    else:
        LOG.warning(f"Unexpected elem bytes: {frame.ucElemBytes}; defaulting to uint8")
        dtype = np.uint8
    arr = np.frombuffer(payload.tobytes(), dtype=dtype)
    channels = max(frame.ucChannels, 1)
    expected = frame.usWidth * frame.usHeight * channels
    if arr.size != expected:
        LOG.warning(f"Element count mismatch: got {arr.size}, expected {expected}")
    try:
        if channels == 1:
            arr = arr.reshape((frame.usHeight, frame.usWidth))
        else:
            arr = arr.reshape((frame.usHeight, frame.usWidth, channels))
        return arr
    except Exception as e:
        LOG.error(f"Reshape failed: {e}")
        return None


def run(args):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    LOG.info(f"Script dir: {script_dir}")

    tucam_init = TUCAM_INIT(0, script_dir.encode('utf-8'))
    ret = TUCAM_Api_Init(pointer(tucam_init), 5000)
    check(ret, "TUCAM_Api_Init")
    LOG.info(f"Camera count reported: {tucam_init.uiCamCount}")
    if tucam_init.uiCamCount < 1:
        LOG.error("No cameras detected.")
        return

    tucam_open = TUCAM_OPEN(0, 0)
    ret = TUCAM_Dev_Open(pointer(tucam_open))
    check(ret, "TUCAM_Dev_Open")
    hcam = tucam_open.hIdxTUCam
    LOG.info(f"Opened camera handle: {hcam}")

    try:
        if args.roi:
            set_roi(hcam, tuple(args.roi))
        if args.exposure is not None:
            set_exposure(hcam, args.exposure)

        frame = TUCAM_FRAME()
        frame.pBuffer = 0
        frame.ucFormatGet = TUFRM_FORMATS.TUFRM_FMT_USUAl.value
        frame.uiRsdSize = 1
        ret = TUCAM_Buf_Alloc(hcam, pointer(frame))
        check(ret, "TUCAM_Buf_Alloc")
        LOG.info("Allocated frame buffer")
        dump_frame_struct(frame, "AfterAlloc")

        ret = TUCAM_Cap_Start(hcam, TUCAM_CAPTURE_MODES.TUCCM_SEQUENCE.value)
        check(ret, "TUCAM_Cap_Start")
        LOG.info("Start capture OK")

        if args.pre_wait > 0:
            LOG.info(f"Pre-wait {args.pre_wait}s to allow camera pipeline to prime")
            time.sleep(args.pre_wait)

        LOG.info("Starting frame acquisition loop...")
        for i in range(args.frames):
            t0 = time.time()
            raw_ret = TUCAM_Buf_WaitForFrame(hcam, pointer(frame), args.timeout)
            dt = (time.time() - t0) * 1000.0
            unsigned_ret = _mask32(raw_ret)
            if not is_success(raw_ret):
                LOG.error(
                    f"Frame {i}: WaitForFrame failed -> {decode_ret(raw_ret)} (elapsed {dt:.1f} ms, raw=0x{unsigned_ret:08X})"
                )
                if args.abort_on_error:
                    break
                continue

            dump_frame_struct(frame, f"Frame{i}")
            LOG.info(
                f"Frame {i}: OK in {dt:.1f} ms | size=({frame.usWidth}x{frame.usHeight}) ch={frame.ucChannels} elemBytes={frame.ucElemBytes} uiImgSize={frame.uiImgSize} header={frame.usHeader}"  # noqa: E501
            )
            arr = frame_to_numpy(frame)
            if arr is not None:
                LOG.info(
                    f"  Stats: dtype={arr.dtype} shape={arr.shape} min={arr.min()} max={arr.max()} mean={arr.mean():.1f}"
                )
            else:
                LOG.warning("  Failed to convert frame to numpy array")
            if args.sleep > 0:
                time.sleep(args.sleep)

        LOG.info("Stopping capture & releasing buffer")
        TUCAM_Buf_AbortWait(hcam)
        TUCAM_Cap_Stop(hcam)
        TUCAM_Buf_Release(hcam)

    finally:
        if hcam:
            TUCAM_Dev_Close(hcam)
        TUCAM_Api_Uninit()
        LOG.info("Clean shutdown complete")


def parse_args():
    p = argparse.ArgumentParser(description="Minimal TUCAM_Buf_WaitForFrame test")
    p.add_argument("--frames", type=int, default=3, help="Number of frames to acquire")
    p.add_argument("--timeout", type=int, default=5000, help="WaitForFrame timeout (ms)")
    p.add_argument("--exposure", type=float, default=0.5, help="Exposure time (seconds)")
    p.add_argument("--roi", nargs=4, type=int, help="ROI: HOffset VOffset Width Height")
    p.add_argument("--sleep", type=float, default=0.0, help="Sleep between frames (s)")
    p.add_argument("--pre-wait", type=float, default=0.15, help="Initial wait after Cap_Start (s)")
    p.add_argument("--abort-on-error", action="store_true", help="Abort loop on first WaitForFrame error")
    p.add_argument("--log-level", default="INFO", help="Logging level")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        run(args)
    except SystemExit:
        raise
    except Exception as e:
        LOG.exception(f"Unhandled exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
