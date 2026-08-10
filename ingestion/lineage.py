"""Wire the ML half of the lineage graph that MLflow ingestion can't infer:

    training_dataset --(input to)--> DataJob: train_fraud_model
                                          |
                                          v  (trainingJobs)
                                     MLModel: fraud_detection_model_1
                                          |
                                          v  (deployments)
                                 MLModelDeployment: fraud_scoring_api

Completes the end-to-end  raw -> feature -> model -> endpoint  chain the agent
walks for root-cause and blast-radius analysis.
"""
from __future__ import annotations

import os
from typing import Optional

import datahub.emitter.mce_builder as builder
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    DataFlowInfoClass,
    DataJobInfoClass,
    DataJobInputOutputClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
)

ENV = "PROD"


class LineageWirer:
    """Emits the model <-> training-data <-> deployment lineage edges."""

    def __init__(self, gms_server: Optional[str] = None) -> None:
        server = gms_server or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
        self.graph = DataHubGraph(DataHubGraphConfig(server=server))

        self.model_urn = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", ENV)
        self.training_dataset_urns = [
            builder.make_dataset_urn("duckdb", "fraud.main.training_dataset", ENV),
            builder.make_dataset_urn("dbt", "fraud_demo.fraud.main.training_dataset", ENV),
        ]
        self.flow_urn = builder.make_data_flow_urn("mlflow", "fraud_training", ENV)
        self.job_urn = builder.make_data_job_urn_with_flow(self.flow_urn, "train_fraud_model")
        self.deploy_urn = builder.make_ml_model_deployment_urn("mlflow", "fraud_scoring_api", ENV)

    def wire(self) -> None:
        mcps: list[MetadataChangeProposalWrapper] = [
            MetadataChangeProposalWrapper(
                entityUrn=self.flow_urn, aspect=DataFlowInfoClass(name="fraud_training")
            ),
            MetadataChangeProposalWrapper(
                entityUrn=self.job_urn,
                aspect=DataJobInfoClass(
                    name="train_fraud_model", type="TRAINING", flowUrn=self.flow_urn
                ),
            ),
            MetadataChangeProposalWrapper(
                entityUrn=self.job_urn,
                aspect=DataJobInputOutputClass(
                    inputDatasets=self.training_dataset_urns, outputDatasets=[]
                ),
            ),
            MetadataChangeProposalWrapper(
                entityUrn=self.deploy_urn,
                aspect=MLModelDeploymentPropertiesClass(
                    description="Batch scoring job serving the champion fraud model.",
                    customProperties={"kind": "batch_scoring", "schedule": "hourly"},
                ),
            ),
        ]

        props = self.graph.get_aspect(self.model_urn, MLModelPropertiesClass) or MLModelPropertiesClass()
        props.trainingJobs = [self.job_urn]
        props.deployments = [self.deploy_urn]
        mcps.append(MetadataChangeProposalWrapper(entityUrn=self.model_urn, aspect=props))

        for mcp in mcps:
            self.graph.emit_mcp(mcp)

        print(f"  wired: training_dataset -> {self.job_urn.split(',')[-1].rstrip(')')} "
              f"-> model -> deployment")


if __name__ == "__main__":
    LineageWirer().wire()
