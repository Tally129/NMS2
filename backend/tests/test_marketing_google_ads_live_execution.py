import pytest

from marketing_os.integrations.google_ads import (
    GoogleAdsIntegration,
)


class EnumValue:
    def __init__(self, name):
        self.name = name


class Enums:
    class CampaignStatusEnum:
        PAUSED = EnumValue("PAUSED")
        ENABLED = EnumValue("ENABLED")

    class AdvertisingChannelTypeEnum:
        SEARCH = "SEARCH"

    class BudgetDeliveryMethodEnum:
        STANDARD = "STANDARD"

    class EuPoliticalAdvertisingStatusEnum:
        DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING = (
            EnumValue(
                "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
            )
        )


class Obj:
    pass


class Operation:
    def __init__(self):
        self.create = Obj()
        self.create.manual_cpc = Obj()
        self.update = Obj()
        self.update_mask = Obj()


class FieldMask:
    def __init__(self, paths=None):
        self.paths = list(paths or [])


class Result:
    def __init__(self, resource_name):
        self.resource_name = resource_name


class Response:
    def __init__(self, resource_name):
        self.results = [Result(resource_name)]


class BudgetService:
    def __init__(self, client):
        self.client = client

    def mutate_campaign_budgets(
        self,
        customer_id,
        operations,
    ):
        op = operations[0]

        if hasattr(op.create, "name"):
            self.client.last_created_budget = op.create

        if hasattr(op.update, "resource_name"):
            self.client.last_updated_budget = op.update

        return Response(
            f"customers/{customer_id}/campaignBudgets/456"
        )


class CampaignService:
    def __init__(self, client):
        self.client = client

    def mutate_campaigns(
        self,
        customer_id,
        operations,
    ):
        op = operations[0]

        if hasattr(op.create, "name"):
            self.client.last_created_campaign = op.create

        if hasattr(op.update, "resource_name"):
            self.client.last_updated_campaign = op.update

        return Response(
            f"customers/{customer_id}/campaigns/123"
        )


class GoogleAdsService:
    def __init__(self, client):
        self.client = client

    def search(
        self,
        customer_id,
        query,
    ):
        if "FROM campaign_budget" in query:
            rows = []

            for item in self.client.reusable_budgets:
                row = Obj()

                row.campaign_budget = Obj()

                row.campaign_budget.id = (
                    item["id"]
                )

                row.campaign_budget.name = (
                    item["name"]
                )

                row.campaign_budget.resource_name = (
                    item["resource_name"]
                )

                row.campaign_budget.amount_micros = (
                    item["amount_micros"]
                )

                row.campaign_budget.reference_count = (
                    item["reference_count"]
                )

                row.campaign_budget.status = (
                    EnumValue(
                        item.get(
                            "status",
                            "ENABLED",
                        )
                    )
                )

                rows.append(row)

            return rows

        row = Obj()

        row.campaign = Obj()
        row.campaign.id = 123
        row.campaign.name = "Test Campaign"
        row.campaign.status = EnumValue("PAUSED")
        row.campaign.campaign_budget = (
            f"customers/{customer_id}/campaignBudgets/456"
        )

        row.campaign_budget = Obj()
        row.campaign_budget.amount_micros = 25000000

        return [row]


class FakeClient:
    def __init__(self):
        self.enums = Enums()
        self.last_created_budget = None
        self.last_created_campaign = None
        self.last_updated_budget = None
        self.last_updated_campaign = None
        self.reusable_budgets = []

    def get_service(self, name):
        if name == "CampaignBudgetService":
            return BudgetService(self)

        if name == "CampaignService":
            return CampaignService(self)

        if name == "GoogleAdsService":
            return GoogleAdsService(self)

        raise AssertionError(name)

    def get_type(self, name):
        if name in {
            "CampaignBudgetOperation",
            "CampaignOperation",
        }:
            return Operation()

        if name == "FieldMask":
            return FieldMask

        raise AssertionError(name)

    def copy_from(self, target, source):
        target.paths = list(source.paths)


@pytest.fixture
def integration():
    client = FakeClient()

    adapter = GoogleAdsIntegration(
        account={
            "external_account_id": "123-456-7890",
            "configuration": {},
        },
        client=client,
    )

    return adapter, client


@pytest.mark.asyncio
async def test_live_campaign_create_defaults_paused(
    integration,
):
    adapter, client = integration

    result = await adapter.execute_action(
        action_type="campaign.create",
        target_type="account",
        target_id=None,
        payload={
            "name": "Weight Management Search",
            "daily_budget": "25.00",
        },
    )

    assert result["external_write_performed"] is True
    assert result["verified"] is True
    assert result["status"] == "paused"

    campaign = client.last_created_campaign

    assert campaign.name == "Weight Management Search"
    assert campaign.status.name == "PAUSED"

    assert (
        campaign
        .contains_eu_political_advertising
        .name
        == "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
    )

    assert result["campaign_budget_reused"] is False
    assert client.last_created_budget is not None


@pytest.mark.asyncio
async def test_live_campaign_create_reuses_exact_orphan_budget(
    integration,
):
    adapter, client = integration

    client.reusable_budgets = [
        {
            "id": 15855573001,
            "name": "NMS API Validation Budget",
            "resource_name": (
                "customers/1234567890/"
                "campaignBudgets/15855573001"
            ),
            "amount_micros": 5000000,
            "reference_count": 0,
            "status": "ENABLED",
        }
    ]

    result = await adapter.execute_action(
        action_type="campaign.create",
        target_type="account",
        target_id=None,
        payload={
            "name": "NMS API Validation",
            "daily_budget": "5.00",
        },
    )

    assert result["external_write_performed"] is True
    assert result["verified"] is True

    assert (
        result["campaign_budget_reused"]
        is True
    )

    assert (
        result["campaign_budget_resource_name"]
        == (
            "customers/1234567890/"
            "campaignBudgets/15855573001"
        )
    )

    assert client.last_created_budget is None

    assert (
        client.last_created_campaign.campaign_budget
        == (
            "customers/1234567890/"
            "campaignBudgets/15855573001"
        )
    )

    assert (
        client.last_created_campaign
        .contains_eu_political_advertising
        .name
        == "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
    )


def test_reusable_budget_ignores_wrong_amount(
    integration,
):
    adapter, client = integration

    client.reusable_budgets = [
        {
            "id": 1,
            "name": "NMS API Validation Budget",
            "resource_name": (
                "customers/1234567890/"
                "campaignBudgets/1"
            ),
            "amount_micros": 6000000,
            "reference_count": 0,
            "status": "ENABLED",
        }
    ]

    resource = (
        adapter
        ._find_reusable_campaign_budget_sync(
            budget_name="NMS API Validation Budget",
            amount_micros=5000000,
        )
    )

    assert resource is None


def test_reusable_budget_ignores_referenced_budget(
    integration,
):
    adapter, client = integration

    client.reusable_budgets = [
        {
            "id": 1,
            "name": "NMS API Validation Budget",
            "resource_name": (
                "customers/1234567890/"
                "campaignBudgets/1"
            ),
            "amount_micros": 5000000,
            "reference_count": 1,
            "status": "ENABLED",
        }
    ]

    resource = (
        adapter
        ._find_reusable_campaign_budget_sync(
            budget_name="NMS API Validation Budget",
            amount_micros=5000000,
        )
    )

    assert resource is None


def test_reusable_budget_rejects_multiple_matches(
    integration,
):
    adapter, client = integration

    client.reusable_budgets = [
        {
            "id": 1,
            "name": "NMS API Validation Budget",
            "resource_name": (
                "customers/1234567890/"
                "campaignBudgets/1"
            ),
            "amount_micros": 5000000,
            "reference_count": 0,
            "status": "ENABLED",
        },
        {
            "id": 2,
            "name": "NMS API Validation Budget",
            "resource_name": (
                "customers/1234567890/"
                "campaignBudgets/2"
            ),
            "amount_micros": 5000000,
            "reference_count": 0,
            "status": "ENABLED",
        },
    ]

    with pytest.raises(
        RuntimeError,
        match="multiple_reusable_campaign_budgets",
    ):
        adapter._find_reusable_campaign_budget_sync(
            budget_name="NMS API Validation Budget",
            amount_micros=5000000,
        )


@pytest.mark.asyncio
async def test_live_campaign_pause(
    integration,
):
    adapter, client = integration

    result = await adapter.execute_action(
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={"reason": "test"},
    )

    assert result["external_write_performed"] is True
    assert result["status"] == "paused"
    assert result["verified"] is True

    assert (
        client.last_updated_campaign.status.name
        == "PAUSED"
    )


@pytest.mark.asyncio
async def test_live_campaign_resume(
    integration,
):
    adapter, client = integration

    result = await adapter.execute_action(
        action_type="campaign.resume",
        target_type="campaign",
        target_id="123",
        payload={"reason": "test"},
    )

    assert result["external_write_performed"] is True
    assert result["status"] == "enabled"
    assert result["verified"] is True

    assert (
        client.last_updated_campaign.status.name
        == "ENABLED"
    )


@pytest.mark.asyncio
async def test_live_budget_update_mutates_existing_budget(
    integration,
):
    adapter, client = integration

    result = await adapter.execute_action(
        action_type="budget.update",
        target_type="campaign",
        target_id="123",
        payload={
            "daily_budget": "35.00",
            "reason": "approved increase",
        },
    )

    assert result["external_write_performed"] is True
    assert result["verified"] is True

    budget = client.last_updated_budget

    assert budget.amount_micros == 35000000
    assert (
        budget.resource_name
        == "customers/1234567890/campaignBudgets/456"
    )


@pytest.mark.asyncio
async def test_live_execution_rejects_unknown_action(
    integration,
):
    adapter, _ = integration

    with pytest.raises(
        ValueError,
        match="unsupported_live_action",
    ):
        await adapter.execute_action(
            action_type="campaign.delete",
            target_type="campaign",
            target_id="123",
            payload={},
        )
