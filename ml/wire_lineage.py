"""Wire the ML half of the lineage graph that MLflow ingestion can't infer:

    training_dataset  --(input to)-->  DataJob: train_fraud_model
                                            |
                                            v  (trainingJobs)
                                        MLModel: fraud_detection_model_1
                                            |
                                            v  (deployments)
                                    MLModelDeployment: fraud_scoring_api

This completes the end-to-end  raw -> feature -> model -> endpoint  chain the
agent walks for root-cause and blast-radius analysis.

Run:  PYTHONIOENCODING=utf-8 python ml/wire_lineage.py
"""
from __future__ import annotations

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
MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", ENV)

TRAINING_DATASET_URNS = [
    builder.make_dataset_urn("duckdb", "fraud.main.training_dataset", ENV),
    builder.make_dataset_urn(
        "dbt", "fraud_demo.fraud.main.training_dataset", ENV
    ),
]

FLOW_URN = builder.make_data_flow_urn("mlflow", "fraud_training", ENV)
JOB_URN = builder.make_data_job_urn_with_flow(FLOW_URN, "train_fraud_model")
DEPLOY_URN = builder.make_ml_model_deployment_urn("mlflow", "fraud_scoring_api", ENV)


def main() -> None:
    g = DataHubGraph(DataHubGraphConfig(server="http://localhost:8080"))

    mcps: list[MetadataChangeProposalWrapper] = [
        # 1) training DataFlow + DataJob
        MetadataChangeProposalWrapper(
            entityUrn=FLOW_URN,
            aspect=DataFlowInfoClass(name="fraud_training"),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=JOB_URN,
            aspect=DataJobInfoClass(
                name="train_fraud_model", type="TRAINING", flowUrn=FLOW_URN
            ),
        ),
        # 2) training_dataset -> DataJob
        MetadataChangeProposalWrapper(
            entityUrn=JOB_URN,
            aspect=DataJobInputOutputClass(
                inputDatasets=TRAINING_DATASET_URNS, outputDatasets=[]
            ),
        ),
        # 3) scoring deployment (the "endpoint")
        MetadataChangeProposalWrapper(
            entityUrn=DEPLOY_URN,
            aspect=MLModelDeploymentPropertiesClass(
                description="Batch scoring job serving the champion fraud model.",
                customProperties={"kind": "batch_scoring", "schedule": "hourly"},
            ),
        ),
    ]

    # 4) update MLModel: preserve existing props, add trainingJobs + deployments
    props = g.get_aspect(MODEL_URN, MLModelPropertiesClass) or MLModelPropertiesClass()
    props.trainingJobs = [JOB_URN]
    props.deployments = [DEPLOY_URN]
    mcps.append(MetadataChangeProposalWrapper(entityUrn=MODEL_URN, aspect=props))

    for mcp in mcps:
        g.emit_mcp(mcp)

    print("Wired ML lineage:")
    print(f"  training_dataset -> {JOB_URN}")
    print(f"  {JOB_URN} -> (trainingJobs) {MODEL_URN}")
    print(f"  {MODEL_URN} -> (deployments) {DEPLOY_URN}")


if __name__ == "__main__":
    main()
