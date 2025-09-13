# BYD Battery Box Dashboard Card

Custom Lovelace card for visualizing BYD Battery Box cell voltages per module.

Installation via HACS (as a Dashboard plugin): add this repository as a custom repository with category "plugin" and select the card. HACS will place the JS file under /www/community/byd_battery_box_dashboard.

Usage example in Lovelace resources:
- url: /hacsfiles/byd_battery_box_dashboard/byd-battery-box-dashboard.js
  type: module

Card example:
- type: custom:byd-battery-box-dashboard
  entity: sensor.bms_1_cells_average_voltage
  days: 3
  towers: 3

The card renders per-module cell min/max of last days (red for min, green for max) and current voltage (green bar). Light gray background shows the module max range over the period.
