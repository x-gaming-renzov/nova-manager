# ADX Service Principal Request

## Context

Our backend runs on GCP Cloud Run and needs to authenticate against the ADX cluster `kresadxdev`. We need a service principal with client credentials.

## Request

App Registration in tenant `1a27bdbf-e6cc-4e33-85d2-e1c81bad930a` with a client secret. Suggested name: `nova-manager-gcp`.

Database Admin on these databases in cluster `kresadxdev`:

```kql
.add database ['kr-es-analytics-dev'] admins ('aadapp={CLIENT_ID};1a27bdbf-e6cc-4e33-85d2-e1c81bad930a')
.add database ['kr-es-analytics-staging'] admins ('aadapp={CLIENT_ID};1a27bdbf-e6cc-4e33-85d2-e1c81bad930a')
.add database ['org_test_db_check'] admins ('aadapp={CLIENT_ID};1a27bdbf-e6cc-4e33-85d2-e1c81bad930a')
.add database ['org_c1c5efad_ec63_4729_b976_3378fc429ce9_app_03c1d3de_7ae4_4bd7_ae11_023fa6306448'] admins ('aadapp={CLIENT_ID};1a27bdbf-e6cc-4e33-85d2-e1c81bad930a')
.add database ['org_fa7b153b_6998_416d_8adc_3e41c3971524_app_6fa6d19b_21e4_44be_8103_7ab1b5324eec'] admins ('aadapp={CLIENT_ID};1a27bdbf-e6cc-4e33-85d2-e1c81bad930a')
```

Please share back the **Application (client) ID** and **client secret value**.

## What We Have

- Tenant ID: `1a27bdbf-e6cc-4e33-85d2-e1c81bad930a`
- Cluster: `kresadxdev` (`https://kresadxdev.centralindia.kusto.windows.net`)
- Resource Group: `KR-ESports-RG-Dev`
