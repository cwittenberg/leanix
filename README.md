# leanix

## Coupa integration
- Facilitates initial load, since standard Coupa API does not filter on custom-fields, approach taken is to pull all POs from a granular IT category
- Based on Suppliers found, all contracts are pulled pertaining to supplier
- Auto-detection implemented for existing Applications and Providers in LeanIX metamodel
- Auto-detection of Amendment vs Contract
- Facilitates currency conversion for contracts in non-group currency (i.e. EUR, using exchangeratesapi.io)
- Downloads contracts zipfile from Coupa, unzips and uploads PDF as Resource to Contract

### TODO
- [ ] Automated scheduling (i.e. using Azure CF)
- [ ] Load also Support and SoW contracts outside of licenses
- [ ] Add RFx detection 
