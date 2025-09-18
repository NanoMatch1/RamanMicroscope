#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal replication of the working TUCam example.

Flow:
  1) Api_Init
  2) Dev_Open(0)
  3) Buf_Alloc (with TUFRM_FMT_USUAl, uiRsdSize=1)
  4) Cap_Start (SEQUENCE)
  5) Loop: Buf_WaitForFrame -> print stats
  6) Buf_AbortWait, Cap_Stop, Buf_Release
  7) Dev_Close, Api_Uninit

ROI/exposure utilities are provided but not used; the calls are commented out.
"""

import argparse
import ctypes
import sys
import time
from ctypes import pointer

# Import the full TUCam Python wrapper (as your example does)
from TUCam import *  # noqa: F401,F403


def decode_ret(code: int) -> str:
    try:
        return f"{TUCAMRET(code).name} ({code})"
    except Exception:
        return f"UNKNOWN_RET ({code})"


# -------- Optional helpers (not called by default) -----------------
def set_exposure_seconds(hcam, seconds: float):
    """Set exposure (seconds). Not used by default."""
    # Disable auto exposure if available
    try:
        TUCAM_Capa_SetValue(hcam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, 0)
    except Exception:
        pass
    ms_val = float(seconds) * 1000.0
    ret = TUCAM_Prop_SetValue(hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, ms_val, 0)
    print(f"Set exposure -> {decode_ret(ret)}")


def set_roi(hcam, h_off: int, v_off: int, width: int, height: int):
    """Set ROI. Not used by default."""
    roi = TUCAM_ROI_ATTR()
    roi.bEnable = 1
    roi.nHOffset = int(h_off)
    roi.nVOffset = int(v_off)
    roi.nWidth = int(width)
    roi.nHeight = int(height)
    ret = TUCAM_Cap_SetROI(hcam, roi)
    print(f"Set ROI ({h_off}, {v_off}, {width}, {height}) -> {decode_ret(ret)}")


# -------------------------------------------------------------------

def run(frames: int, timeout_ms: int, verbose: bool):
    # 1) Init API (mirror example: config path = script dir)
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tucam_init = TUCAM_INIT(0, script_dir.encode("utf-8"))
    ret = TUCAM_Api_Init(pointer(tucam_init), 5000)
    print(f"TUCAM_Api_Init -> {decode_ret(ret)}")
    print(f"Camera count: {tucam_init.uiCamCount}")

    if ret != TUCAMRET.TUCAMRET_SUCCESS or tucam_init.uiCamCount < 1:
        print("No camera available or init failed.")
        # Ensure uninit even on early exit
        try:
            TUCAM_Api_Uninit()
        except Exception:
            pass
        sys.exit(2)

    # 2) Open first camera
    tucam_open = TUCAM_OPEN(0, 0)
    ret = TUCAM_Dev_Open(pointer(tucam_open))
    print(f"TUCAM_Dev_Open -> {decode_ret(ret)}")
    hcam = tucam_open.hIdxTUCam
    if not hcam:
        print("Open camera failed.")
        TUCAM_Api_Uninit()
        sys.exit(2)
    else:
        print("Open camera success!")

    try:
        # --- Optional config (commented out to exactly mirror the example) ---
        # set_exposure_seconds(hcam, 0.5)
        # set_roi(hcam, 0, 0, 2048, 148)
        # ---------------------------------------------------------------------

        # 3) Allocate buffer (mirror example fields)
        frame = TUCAM_FRAME()
        frame.pBuffer = 0
        # Important: some SDK versions spell this differently; we copy the example
        frame.ucFormatGet = TUFRM_FORMATS.TUFRM_FMT_USUAl.value
        frame.uiRsdSize = 1

        ret = TUCAM_Buf_Alloc(hcam, pointer(frame))
        print(f"TUCAM_Buf_Alloc -> {decode_ret(ret)}")
        if ret != TUCAMRET.TUCAMRET_SUCCESS:
            raise RuntimeError("Buffer alloc failed")

        # 4) Start capture (sequence)
        ret = TUCAM_Cap_Start(hcam, TUCAM_CAPTURE_MODES.TUCCM_SEQUENCE.value)
        print(f"TUCAM_Cap_Start(SEQUENCE) -> {decode_ret(ret)}")
        if ret != TUCAMRET.TUCAMRET_SUCCESS:
            raise RuntimeError("Cap_Start failed")

        # 5) Acquire frames
        n = int(frames)
        for i in range(n):
            t0 = time.time()
            ret = TUCAM_Buf_WaitForFrame(hcam, pointer(frame), int(timeout_ms))
            dt = (time.time() - t0) * 1000.0
            if ret != TUCAMRET.TUCAMRET_SUCCESS:
                print(f"[{i}] WaitForFrame -> {decode_ret(ret)}  (elapsed {dt:.1f} ms)")
                continue

            # Mirror example print
            print(
                "Grab the frame success, index number is %d, "
                "width:%d, height:%d, channel:%d, elembytes:%d, image size:%d"
                % (
                    i,
                    frame.usWidth,
                    frame.usHeight,
                    frame.ucChannels,
                    frame.ucElemBytes,
                    frame.uiImgSize,
                )
            )
            if verbose:
                print(
                    f"    header:{frame.usHeader} pitch:{frame.usLinePitch} "
                    f"elapsed:{dt:.1f} ms"
                )

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        # 6) Abort/Stop/Release (mirror example order)
        try:
            TUCAM_Buf_AbortWait(hcam)
            print("Buf_AbortWait -> OK")
        except Exception as _:
            pass
        try:
            TUCAM_Cap_Stop(hcam)
            print("Cap_Stop -> OK")
        except Exception as _:
            pass
        try:
            TUCAM_Buf_Release(hcam)
            print("Buf_Release -> OK")
        except Exception as _:
            pass

        # 7) Close & Uninit
        try:
            TUCAM_Dev_Close(hcam)
            print("Close the camera success")
        except Exception as _:
            pass
        try:
            TUCAM_Api_Uninit()
            print("Api_Uninit -> OK")
        except Exception as _:
            pass


def parse_args():
    ap = argparse.ArgumentParser(description="Minimal TUCam working-example replica")
    ap.add_argument("--frames", type=int, default=10, help="Number of frames to grab")
    ap.add_argument("--timeout", type=int, default=1000, help="WaitForFrame timeout (ms)")
    ap.add_argument("--verbose", action="store_true", help="Print extra frame fields")
    return ap.parse_args()


def main():
    args = parse_args()
    run(args.frames, args.timeout, args.verbose)


if __name__ == "__main__":
    main()
