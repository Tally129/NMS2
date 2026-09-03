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
