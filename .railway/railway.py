from railway_sdk import define_railway, github, project, service
# This repository manages only its own resources in the environment. Other
# repositories export their own partial name.
# See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
PARTIAL = "fomc-tone-lab"
@define_railway
def main(ctx=None):
    fomcToneLab = service(
        "fomc-tone-lab",
        source=github("flukier1016/fomc-tone-duration", **{ "branch": "main", "checkSuites": False }),
        build={ "buildEnvironment": "V3", "builder": "DOCKERFILE", "dockerfilePath": "deploy/Dockerfile" },
        healthcheck="/api/health",
        healthcheckTimeout=120,
        replicas={ "us-east4-eqdc4a": 1 },
    )
    return project("FOMC Tone Lab", variables={"managed": False}, resources=[fomcToneLab])
