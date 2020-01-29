# Mini Fuzz

This is an ongoing project to build a standalone table-top music player with headphone output.

## Goals

- Be standalone – A device to play my music and do nothing else
- Be small (in physical size) – A device that fits onto my desk without occupying much space
- Be big (in storage size) – A device that contains _all_ my music
- Be old-school – A device with mechanical controls for enjoyable operation

## Components

- Raspberry Pi Zero W
- JustBoom DAC Zero pHAT
- ILI9341 240x320 RGB TFT LCD display

## Current State

- [ ] Physical components
  - [x] Stacking header soldering
  - [x] DAC pHAT stacking
  - [x] Display wiring
  - [ ] Button wiring
  - [ ] Volume slider wiring
  - [ ] Rotary encoder wiring
  - [ ] Case
- [ ] UI
  - [x] Playback screen
     - [x] Current track info (artist, album, title)
     - [x] Cover view
     - [x] Track progress bar
     - [x] Volume meter
     - [x] Playback controls
  - [ ] Library screen
  - [ ] Playlist screen
  - [ ] Screen transitions

I started redoing the main event loop so the code is currently somewhat borked.

![](Photos/2020-01-29.jpg)

## Wiring

```
LED Panel   | Raspberry Pi (Physical Pin)
------------+-----------------------------
SOCK (MISO) | 21
LED         | 10
SCK         | 23
SDI (MOSI)  | 19
DC          | 18
RESET       | 22
CS          | 24
GND         |  6
VCC         |  1
```

```
┌───────────────────────┐
│┌─────────────────────┐│
││┌───────────────────┐││
│││┌─────────────────┐│││
││││                 ││││
│││└── 01 02 ─       ││└│── SOCK (MISO)
│││  ─ 03 04 ─  ┌────││─│── LED
│││  ─ 05 06 ───│───┐││ └── SCK
│││  ─ 07 08 ─  │   ││└──── SDI (MOSI)
│││  ─ 09 10 ───┘┌──││───── DC
│││  ─ 11 12 ─   │┌─││───── RESET
│││  ─ 13 14 ─   ││┌││───── CS
│││  ─ 15 16 ─   │││└│───── GND
│││  ─ 17 18 ────┘││ └───── VCC
││└─── 19 20 ─    ││
│└──── 21 22 ─────┘│
└───── 23 24 ──────┘
     ─ 25 26 ─
     ─ 27 28 ─
     ─ 29 30 ─
     ─ 31 32 ─
     ─ 33 34 ─
     ─ 35 36 ─
     ─ 37 38 ─
     ─ 39 40 ─
```

## License

Mini Fuzz is licensed under the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

The Inconsolata font is subject to the Open Font License.
