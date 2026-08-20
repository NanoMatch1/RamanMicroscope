"""
TRIAX spectrometer connection diagnostic script.

Runs standalone — does NOT require the full microscope/interface stack.
Run from the RamanMicroscope root:
    python instruments/triax_connection_test.py

Probes every VISA resource and logs exhaustive detail at each step so you
can see exactly where the communication breaks down.
"""

import time
import sys

try:
    import pyvisa
except ImportError:
    print("ERROR: pyvisa is not installed. Run: pip install pyvisa")
    sys.exit(1)


# ── configuration ─────────────────────────────────────────────────────────────

PROBE_TIMEOUT_MS   = 2000   # timeout used when probing each resource
FLUSH_TIMEOUT_MS   = 200    # short timeout used when draining stale buffer data
FLUSH_MAX_READS    = 20     # safety cap on flush loop iterations
POST_WRITE_DELAY_S = 0.1    # wait after each write before reading

# Commands from the TRIAX message map
CMD_GET_POSITION   = 'H0'   # query grating position  → expected response: 'H<digits>'
CMD_INIT           = 'A'    # full initialise          → very slow, only run if asked
CMD_COMSMODE       = '02000' # set comms mode

KNOWN_GPIB_ADDRESSES = [
    'GPIB0::1::INSTR',   # default TRIAX address
    'GPIB0::2::INSTR',
    'GPIB0::5::INSTR',
    'GPIB1::1::INSTR',
]

SEPARATOR = '-' * 70


# ── helpers ────────────────────────────────────────────────────────────────────

def log(msg):
    print(msg)
    sys.stdout.flush()


def flush_buffer(resource, label=''):
    """Drain stale data from the VISA read buffer. Returns a list of flushed strings."""
    original_timeout = resource.timeout
    resource.timeout = FLUSH_TIMEOUT_MS
    flushed = []
    try:
        for _ in range(FLUSH_MAX_READS):
            try:
                stale = resource.read()
                flushed.append(repr(stale))
            except pyvisa.errors.VisaIOError:
                break  # buffer empty
    finally:
        resource.timeout = original_timeout

    if flushed:
        log('  [FLUSH{}] Drained {} message(s): {}'.format(
            ' ' + label if label else '', len(flushed), ', '.join(flushed)))
    else:
        log('  [FLUSH{}] Buffer was clean.'.format(' ' + label if label else ''))
    return flushed


def safe_write_read(resource, command, delay_s=POST_WRITE_DELAY_S):
    """Write a command, wait, then read. Returns (response_str | None, error_str | None)."""
    log('  >> write: {!r}'.format(command))
    try:
        resource.write(command)
    except pyvisa.errors.VisaIOError as exc:
        return None, 'Write error: {}'.format(exc)

    time.sleep(delay_s)

    try:
        response = resource.read()
        log('  << read:  {!r}'.format(response))
        return response, None
    except pyvisa.errors.VisaIOError as exc:
        log('  << read timeout / error: {}'.format(exc))
        return None, 'Read error: {}'.format(exc)


def probe_resource(rm, address):
    """Full diagnostic probe of a single VISA resource address."""
    log('')
    log(SEPARATOR)
    log('Probing: {}'.format(address))
    log(SEPARATOR)

    # ── open ──────────────────────────────────────────────────────────────────
    try:
        resource = rm.open_resource(address)
        log('  Opened successfully.')
    except pyvisa.errors.VisaIOError as exc:
        log('  FAILED to open: {}'.format(exc))
        return

    resource.timeout = PROBE_TIMEOUT_MS

    # ── resource info ─────────────────────────────────────────────────────────
    try:
        log('  Interface type : {}'.format(resource.interface_type))
    except Exception:
        pass
    try:
        log('  Resource name  : {}'.format(resource.resource_name))
    except Exception:
        pass
    try:
        log('  Resource class : {}'.format(resource.resource_class))
    except Exception:
        pass

    # ── flush before anything else ────────────────────────────────────────────
    log('')
    log('  [Step 1] Flushing read buffer before any writes...')
    flush_buffer(resource, 'before')

    # ── log current termination settings ─────────────────────────────────────
    log('')
    log('  [Step 2] Current VISA termination settings...')
    log('  read_termination  : {!r}'.format(resource.read_termination))
    log('  write_termination : {!r}'.format(resource.write_termination))

    # ── try *IDN? with default termination ────────────────────────────────────
    log('')
    log('  [Step 3] Sending *IDN? with DEFAULT termination...')
    idn_response, idn_error = safe_write_read(resource, '*IDN?')
    if idn_response is not None:
        log('  IDN response      : {!r}'.format(idn_response))
        log('  Trailing bytes    : {}'.format([hex(b) for b in idn_response.encode('latin-1', errors='replace')[-4:]]))
    else:
        log('  No IDN response: {}'.format(idn_error))

    flush_buffer(resource, 'post-IDN')

    # ── H0 with default termination ───────────────────────────────────────────
    log('')
    log('  [Step 4] Sending H0 with DEFAULT read_termination ({!r})...'.format(resource.read_termination))
    h0_response, h0_error = safe_write_read(resource, CMD_GET_POSITION, delay_s=0.3)
    if h0_response is not None:
        log('  H0 response : {!r}'.format(h0_response))
    else:
        log('  H0 timed out ({}). Likely a terminator mismatch.'.format(h0_error))

    flush_buffer(resource, 'post-H0-default')

    # ── H0 with read_bytes (bypasses terminator entirely) ────────────────────
    log('')
    log('  [Step 5] Sending H0 then read_bytes() (bypasses terminator check)...')
    log('  >> write: {!r}'.format(CMD_GET_POSITION))
    try:
        resource.write(CMD_GET_POSITION)
        time.sleep(0.3)
        raw = resource.read_bytes(32, break_on_termchar=True)
        log('  << read_bytes raw : {!r}'.format(raw))
        log('  << hex            : {}'.format([hex(b) for b in raw]))
    except pyvisa.errors.VisaIOError as exc:
        log('  read_bytes() failed: {}'.format(exc))
    except AttributeError:
        log('  read_bytes() not available on this resource type.')

    flush_buffer(resource, 'post-read-bytes')

    # ── H0 with CR-only read termination ─────────────────────────────────────
    log('')
    log('  [Step 6] Switching read_termination to CR (\\r) then sending H0...')
    log('  (TRIAX responses to *IDN? ended with \\r — this is likely the fix)')
    resource.read_termination = '\r'
    log('  read_termination now: {!r}'.format(resource.read_termination))
    h0_cr_response, h0_cr_error = safe_write_read(resource, CMD_GET_POSITION, delay_s=0.3)
    if h0_cr_response is not None:
        log('  H0 (CR term) response : {!r}'.format(h0_cr_response))
        if h0_cr_response.strip().startswith('H') and h0_cr_response.strip()[1:].isdigit():
            log('  *** SUCCESS *** TRIAX position = {} steps'.format(h0_cr_response.strip()[1:]))
            log('  FIX: set resource.read_termination = chr(13)  i.e. \\r  before communicating.')
        else:
            log('  Response received but unexpected format.')
            log('  Hex: {}'.format([hex(b) for b in h0_cr_response.encode('latin-1', errors='replace')]))
    else:
        log('  Still no response with CR terminator: {}'.format(h0_cr_error))

    flush_buffer(resource, 'post-H0-cr')

    # ── H0 with CRLF read termination ─────────────────────────────────────────
    log('')
    log('  [Step 7] Switching read_termination to CRLF (\\r\\n) then sending H0...')
    resource.read_termination = '\r\n'
    h0_crlf_response, h0_crlf_error = safe_write_read(resource, CMD_GET_POSITION, delay_s=0.3)
    if h0_crlf_response is not None:
        log('  H0 (CRLF term) response : {!r}'.format(h0_crlf_response))
    else:
        log('  No response with CRLF terminator: {}'.format(h0_crlf_error))

    flush_buffer(resource, 'post-H0-crlf')

    # ── try comsmode command then H0 (back on CR termination) ────────────────
    log('')
    log('  [Step 8] Sending TRIAX comsmode command {!r} then H0...'.format(CMD_COMSMODE))
    log('  (Some TRIAX configs require comsmode to be set before other commands respond)')
    resource.read_termination = '\r'
    comsmode_response, _ = safe_write_read(resource, CMD_COMSMODE, delay_s=0.3)
    log('  Comsmode response: {!r}'.format(comsmode_response))
    flush_buffer(resource, 'post-comsmode')
    h0_post_comsmode, h0_post_error = safe_write_read(resource, CMD_GET_POSITION, delay_s=0.3)
    if h0_post_comsmode is not None:
        log('  H0 post-comsmode response : {!r}'.format(h0_post_comsmode))
        if h0_post_comsmode.strip().startswith('H') and h0_post_comsmode.strip()[1:].isdigit():
            log('  *** SUCCESS *** TRIAX position = {} steps'.format(h0_post_comsmode.strip()[1:]))
    else:
        log('  No response after comsmode: {}'.format(h0_post_error))

    flush_buffer(resource, 'post-comsmode-H0')

    # ── try WHERE AM I (from original connect()) ──────────────────────────────
    log('')
    log('  [Step 9] Sending original connect command "WHERE AM I"...')
    resource.read_termination = '\r'
    wai_response, wai_error = safe_write_read(resource, 'WHERE AM I', delay_s=0.3)
    log('  Response: {!r}  error: {}'.format(wai_response, wai_error))

    flush_buffer(resource, 'post-WAI')

    # ── write_termination = '\r' (CR only, no LF) ─────────────────────────────
    # Most likely fix: TRIAX firmware expects CR-only termination on write.
    # *IDN? works because it is handled by the GPIB IEEE 488.2 layer, which
    # does not depend on the write_termination setting. All TRIAX application
    # commands (H0, WHERE AM I, etc.) go through the firmware, which may reject
    # commands terminated with \r\n.
    log('')
    log('  [Step 10] Setting write_termination=CR only (\\r), read_termination=None...')
    resource.write_termination = '\r'
    resource.read_termination = None
    log('  write_termination now: {!r}'.format(resource.write_termination))
    h0_wr_response, h0_wr_error = safe_write_read(resource, CMD_GET_POSITION, delay_s=0.5)
    if h0_wr_response is not None:
        log('  H0 response : {!r}'.format(h0_wr_response))
        if h0_wr_response.strip().startswith('H') and h0_wr_response.strip()[1:].isdigit():
            log('  *** SUCCESS *** write_termination=\\r is the fix. position={}'.format(h0_wr_response.strip()[1:]))
    else:
        log('  No response: {}'.format(h0_wr_error))
    flush_buffer(resource, 'post-wr-cr')

    # ── write_termination = '\r', read_termination = '\r' ────────────────────
    log('')
    log('  [Step 11] write_termination=CR, read_termination=CR...')
    resource.write_termination = '\r'
    resource.read_termination = '\r'
    h0_both_cr, h0_both_cr_error = safe_write_read(resource, CMD_GET_POSITION, delay_s=0.5)
    if h0_both_cr is not None:
        log('  H0 response : {!r}'.format(h0_both_cr))
        if h0_both_cr.strip().startswith('H') and h0_both_cr.strip()[1:].isdigit():
            log('  *** SUCCESS *** write=\\r read=\\r. position={}'.format(h0_both_cr.strip()[1:]))
    else:
        log('  No response: {}'.format(h0_both_cr_error))
    flush_buffer(resource, 'post-both-cr')

    # ── write_raw: send exact bytes with no terminator at all ─────────────────
    # Rules out any terminator issue entirely — sends the raw bytes H,0 + EOI
    log('')
    log('  [Step 12] write_raw (no terminator, raw bytes only) + read_raw...')
    resource.read_termination = None
    try:
        resource.write_raw(CMD_GET_POSITION.encode())
        time.sleep(0.5)
        raw_response = resource.read_raw()
        log('  read_raw response : {!r}'.format(raw_response))
        log('  hex               : {}'.format([hex(b) for b in raw_response]))
    except pyvisa.errors.VisaIOError as exc:
        log('  write_raw/read_raw failed: {}'.format(exc))
    flush_buffer(resource, 'post-raw')

    # ── write_raw with explicit CR appended ───────────────────────────────────
    log('')
    log('  [Step 13] write_raw with explicit CR byte appended (b"H0\\r")...')
    resource.read_termination = None
    try:
        resource.write_raw(CMD_GET_POSITION.encode() + b'\r')
        time.sleep(0.5)
        raw_response2 = resource.read_raw()
        log('  read_raw response : {!r}'.format(raw_response2))
        log('  hex               : {}'.format([hex(b) for b in raw_response2]))
        decoded = raw_response2.decode('latin-1', errors='replace').strip()
        if decoded.startswith('H') and decoded[1:].isdigit():
            log('  *** SUCCESS *** write_raw + CR byte is the fix. position={}'.format(decoded[1:]))
    except pyvisa.errors.VisaIOError as exc:
        log('  write_raw(H0\\r)/read_raw failed: {}'.format(exc))
    flush_buffer(resource, 'post-raw-cr')

    resource.close()
    log('  Resource closed.')


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    log('=' * 70)
    log('TRIAX Spectrometer Connection Diagnostic')
    log('pyvisa version: {}'.format(pyvisa.__version__))
    log('=' * 70)

    rm = pyvisa.ResourceManager()

    # ── list all visible resources ─────────────────────────────────────────────
    log('')
    log('[VISA Resource Manager]')
    try:
        all_resources = rm.list_resources()
        log('All visible resources ({}):'.format(len(all_resources)))
        for r in all_resources:
            log('  {}'.format(r))
    except Exception as exc:
        log('Failed to list resources: {}'.format(exc))
        all_resources = ()

    # ── separate GPIB from everything else ────────────────────────────────────
    gpib_found    = [r for r in all_resources if 'GPIB' in r.upper()]
    non_gpib      = [r for r in all_resources if 'GPIB' not in r.upper()]

    if non_gpib:
        log('')
        log('Non-GPIB resources (skipped): {}'.format(non_gpib))

    # ── also include hard-coded known addresses even if not auto-listed ────────
    addresses_to_probe = list(gpib_found)
    for addr in KNOWN_GPIB_ADDRESSES:
        if addr not in addresses_to_probe:
            addresses_to_probe.append(addr)
            log('  Adding known address not in auto-list: {}'.format(addr))

    if not addresses_to_probe:
        log('')
        log('ERROR: No GPIB resources found and no fallback addresses reachable.')
        log('Check: NI-VISA / Keysight VISA installed? GPIB card/USB-GPIB adapter detected?')
        sys.exit(1)

    log('')
    log('Addresses to probe ({}): {}'.format(len(addresses_to_probe), addresses_to_probe))

    # ── probe each ────────────────────────────────────────────────────────────
    for address in addresses_to_probe:
        probe_resource(rm, address)

    log('')
    log('=' * 70)
    log('Diagnostic complete.')
    log('=' * 70)


if __name__ == '__main__':
    main()
