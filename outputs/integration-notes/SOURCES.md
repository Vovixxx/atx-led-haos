# Sources and reference material

## Local evidence

- Hub: http://192.168.1.50
- Web interface: `/dali/devices`
- Inspected scripts: `/dali/static/js/base.js`, `/dali/static/js/.mini.js` (selected findings preserved in API and brightness notes; full source not archived).
- Verified JSON snapshots and direct-query results accompany these notes.
- Five user screenshots are copied into `references/` with descriptive filenames.

## Vendor documents

- User-supplied cut sheet: https://cdn.shopify.com/s/files/1/0897/9608/3996/files/ATX_Cut_Sheet_ATX_LED_Smart_Hub_Rev4_WEB.pdf?v=1748656265
- ATX Hub/API manual: https://atxled.com/pdf/ATX%20LED%20Hub.pdf
- AL-DALI-Pi: https://atxled.com/pdf/AL-DALI-Pi.pdf
- HAT serial protocol: https://atxled.com/pdf/AL-DALI-HAT.pdf
- Pi product and examples: https://atxled.com/Pi/
- Vendor sample script referenced by documentation: http://atxled.com/Pi/API_OnOff.py (not executed).
- Hue option discussed but not selected: https://atxled.com/Hue/

The cut sheet was supplied as a link; its full contents were not successfully retrieved during the earlier research. The user's later screenshots directly supplied the API and serial packet documentation.

## DALI and Home Assistant references

- DALI terminology: https://www.dali-alliance.org/about-us/terms.html
- DALI command list: https://infosys.beckhoff.com/content/1033/tcplclib_tc3_dali/18875065611.html
- ABB status-bit explanation: https://library.e.abb.com/public/b5459a15dc4646a1a3d4b2e915aed9dc/OnlineTraining-KNX-DALI-Gateways-Practical-knowledge-about-DALI-OLS-Part1-Nov2021_PR_EN_V1-0_9AKK108466A2493.pdf
- HA integration structure: https://developers.home-assistant.io/docs/creating_integration_file_structure/
- HA manifest: https://developers.home-assistant.io/docs/creating_integration_manifest/
- HA config flows: https://developers.home-assistant.io/docs/core/integration/yaml_configuration/

External documentation is reference material, not authorization to execute its examples.
