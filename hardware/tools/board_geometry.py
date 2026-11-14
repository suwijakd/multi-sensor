"""Shared mechanical numbers for the PCB (gen_pcb.py) and the case (gen_case.py).

All in mm. Board XY: origin at the board's top-left corner seen from the
component (top) side, X right, Y down. The antenna is at the Y = 0 edge and the
strap runs along Y. Heights are measured up from the skin-side surface of the case.
"""

# ---- board ----
PCB_W = 36.0
PCB_H = 42.0
PCB_T = 1.0
NOTCH = 4.4            # square notch at each corner for the case screw posts

# ---- parts that the case has to line up with (board XY) ----
MODULE_X, MODULE_Y = 18.0, 7.75          # MDBT50Q centre; body is 10.5 x 15.5, antenna toward Y = 0
ANT_KEEPOUT = (4.4, -1.0, 31.6, 3.75)    # no copper at all here (x0, y0, x1, y1); ends where the module pads start

LED_X, LED_Y = 8.4, 6.6                  # RGB LED, shines up through a hole in the lid

USB_OVERHANG = 1.25                      # connector front sticks out past the board edge
USB_X, USB_Y = PCB_W - 2.45, 25.6        # USB-C origin; the mouth faces +X (right edge)
USB_BODY_W, USB_BODY_H = 8.94, 3.26      # shell width (along Y) and height above the board

E_Y = 17.5                               # both electrode screws
E1_X, E2_X = 32.5, 3.5                   # E1 = driven electrode (right), E2 = sense electrode (left)

JACK_X, JACK_Y = 3.1, 23.0               # JST-SH jack for external electrodes, mouth faces -X, 0.5 mm inside the edge
SW_X = 2.4                               # top-push switches (B3U-1000P), pressed from the lid
SW_USER_Y, SW_RESET_Y = 29.0, 34.2
H_SW = 1.6                               # switch height above the board, plunger included

BATPAD_X, BATPAD_Y = 31.8, 34.6          # LiPo solder pads (+ on the left)

PPG_X, PPG_Y = 18.0, 26.0                # MAXM86161 on the skin side
PPG_BODY = (2.9, 4.3, 1.4)               # width (X), length (Y), height
PPG_VIA_KEEPOUT = (16.3, 23.6, 19.7, 28.4)

TEMP_X, TEMP_Y = 7.0, 36.5               # TMP117 on the skin side
TEMP_BODY = (2.0, 2.0, 0.8)
TEMP_KEEPOUT = (5.0, 34.5, 9.0, 38.5)

SWD_X, SWD_Y = 18.0, 40.2                # six test pads on the skin side

# ---- battery (sits above the low parts, held in the lid) ----
BAT_W, BAT_L, BAT_T = 20.0, 30.0, 5.0    # 502030 cell
BAT_X0, BAT_Y0 = 8.0, 11.0               # top-left corner of the cell over the board
BAT_GAP = 2.4                            # underside of the cell above the board top (clears the module shield)

# ---- tallest parts on the top side (mm above the board) ----
H_MODULE = 2.1
H_USB = 3.26
