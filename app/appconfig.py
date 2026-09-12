"""Read the component registry from AWS AppConfig."""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class AppConfigReader:
    """Fetches one configuration document through a short-lived session."""

    def __init__(
        self,
        *,
        region: str,
        application: str,
        environment: str,
        profile: str,
    ) -> None:
        self.client = boto3.client("appconfigdata", region_name=region)
        self.application = application
        self.environment = environment
        self.profile = profile

    def read_text(self, _key: str = "") -> str:
        try:
            session = self.client.start_configuration_session(
                ApplicationIdentifier=self.application,
                EnvironmentIdentifier=self.environment,
                ConfigurationProfileIdentifier=self.profile,
            )
            response = self.client.get_latest_configuration(
                ConfigurationToken=session["InitialConfigurationToken"]
            )
            configuration = response["Configuration"].read()
        except (BotoCoreError, ClientError, KeyError) as exc:
            raise RuntimeError("Unable to read the AppConfig registry.") from exc
        if not configuration:
            raise RuntimeError("AppConfig returned an empty registry document.")
        return str(configuration.decode("utf-8"))
