"""Switch billing off for the demo's project once the month's spend passes its budget.

A Cloud Billing budget publishes its status to the Pub/Sub topic `billing-cap` several times a day. This function
reads it and, when the spend so far (after free tiers and credits) is over the budget, unlinks the project from its
billing account: every service in the project stops until billing is linked again (`gcloud billing projects link`).
A message with the attribute `dry_run=true` changes nothing; it reports what would happen and whether the function
holds the permission it needs.
"""

import base64
import json
import os

import functions_framework
from google.cloud import billing_v1, resourcemanager_v3

PROJECT = os.environ["CAP_PROJECT"]
NEEDED = "resourcemanager.projects.deleteBillingAssignment"


@functions_framework.cloud_event
def cap(event):
    message = event.data["message"]
    status = json.loads(base64.b64decode(message["data"]))
    cost, budget = float(status["costAmount"]), float(status["budgetAmount"])
    name = f"projects/{PROJECT}"
    if (message.get("attributes") or {}).get("dry_run") == "true":
        held = resourcemanager_v3.ProjectsClient().test_iam_permissions(resource=name, permissions=[NEEDED]).permissions
        verdict = "would switch billing off" if cost > budget else "would do nothing"
        print(f"dry run: spend {cost} of {budget}; {verdict}; allowed to: {NEEDED in held}")
        return
    if cost <= budget:
        print(f"spend {cost} within the budget of {budget}: nothing to do")
        return
    client = billing_v1.CloudBillingClient()
    if client.get_project_billing_info(name=name).billing_enabled:
        unlinked = billing_v1.ProjectBillingInfo(billing_account_name="")
        client.update_project_billing_info(name=name, project_billing_info=unlinked)
        print(f"spend {cost} over the budget of {budget}: billing switched off for {PROJECT}")
