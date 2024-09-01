# leanix

## Coupa integration
Purpose:
- Load contracts from Coupa into LeanIX such that Architects/those responsible can receive notifications about when an opportunity arises to make a (commercial) transition in view of roadmap

How it works:
- Facilitates initial load, since standard Coupa API does not filter on custom-fields that contain granular commodity codes (as is common practice), approach taken is to pull all POs from a granular IT category
- Based on Suppliers found from all POs in the granular commodity category, all contracts are pulled pertaining to each supplier
- Sanitized Contracts are uploaded to LeanIX via GraphQL

Features:
- Auto-detection for existing Applications and Providers in LeanIX metamodel during load
- Auto-detection of Amendment vs Contract factsheet sub-types
- Facilitates currency conversion for contracts in non-group currency (i.e. EUR, using exchangeratesapi.io)
- Downloads contracts zipfile from Coupa, unzips and uploads PDF as Resource to Contract

TODO: 
- [ ] Automated scheduling (i.e. using Azure CF)
- [ ] Load also Support and SoW contracts outside of licenses
- [ ] Add RFx detection 
- [ ] Update IT Components with Cost from contracts
