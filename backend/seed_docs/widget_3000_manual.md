# Widget-3000 Technical Service Manual (excerpt)

## 1. Product Overview
Model: Widget-3000, Part Number WG3K-A2. This manual covers routine maintenance and
Level-1 troubleshooting for the Widget-3000 industrial controller.

## 2. Specifications
- Operating voltage: 24 V DC (+/- 10%).
- Peak current draw: 3.5 A.
- Operating temperature: -10 C to +55 C.
- Firmware: WG3K-FW v4.2 or later.
- Communication: Modbus TCP on port 502, and RS-485 at 115200 baud, 8N1.

## 3. Boot Sequence
On power-up the Widget-3000 executes:
1. Power-On Self Test (POST), duration ~2 seconds; STATUS LED blinks amber.
2. Firmware integrity check against signature block WG3K-SIG.
3. Configuration load from flash region CFG-A (fallback CFG-B if CRC fails).
4. Network stack initialization and DHCP request.
5. Application start; STATUS LED becomes solid green when READY.
If STATUS remains amber for more than 30 seconds after boot, refer to section 5.

## 4. Routine Maintenance
Every 90 days:
- Verify airflow through the top vent, clear dust with dry compressed air below 30 psi.
- Inspect terminal block TB-1 for loosening; torque to 0.5 Nm.
- Confirm firmware is current using command `wg3k-cli fw --check`.

## 5. Fault Codes and Recovery
| Code | LED Pattern       | Meaning                    | Action                                  |
|------|-------------------|----------------------------|-----------------------------------------|
| E01  | 1 red blink       | POST hardware failure      | Replace unit (see RMA process).         |
| E02  | 2 red blinks      | Firmware signature invalid | Reflash with WG3K-FW-RECOVERY image.    |
| E03  | 3 red blinks      | Config CRC error           | Restore from CFG-B via `wg3k-cli restore`. |
| E04  | 4 red blinks      | Network link down          | Check cable and switch port.            |
| E05  | 5 red blinks      | Over-temperature           | Improve cooling; check ambient temp.    |

## 6. Firmware Update Procedure
1. Download image from portal.acme.com/wg3k/firmware.
2. Verify SHA-256 against the published value.
3. Connect via RS-485 or Modbus TCP.
4. Run `wg3k-cli fw --update <path>`; do not remove power during the ~90 second update.
5. Unit reboots automatically. Confirm the new version with `wg3k-cli fw --check`.

## 7. Safety
Always de-energize the Widget-3000 before removing the front cover. Capacitors on board may
retain charge for up to 60 seconds after power-off. Refer to safety notice SN-WG3K-01.
