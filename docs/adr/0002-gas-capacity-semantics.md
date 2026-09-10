# Gas capacity recorded into installed_capacity despite mixed units

`Gas_Producer` has no `installed_capacity` column; its `gas_production_capacity` is a production rate in kWh/h, not electrical capacity in kW. We copy that value into `installed_capacity` so gas rows join the same schema and marts, and keep the original attribute as a normalized parameter.

Consequence: gas's share of "total installed capacity" mixes kW and kWh/h units; treated as acceptable for uniform reporting. Rejected keeping the field NULL (breaks the unified schema the spec mandates) and excluding the file (drops real data).