"""Entry point:  python -m governance"""
from governance.policy import GovernanceApplier

if __name__ == "__main__":
    GovernanceApplier().apply()
