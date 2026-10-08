"""One reviewed project-status source for the local panel and generated phase guide."""

from pathlib import Path
from typing import Literal

from pydantic import model_validator

from .models import Contract, NonEmpty

Status = Literal["completed", "partial", "in_progress", "blocked", "not_started"]


class Delivery(Contract):
    version: NonEmpty
    title: NonEmpty
    status: Status


class Phase(Contract):
    id: NonEmpty
    title: NonEmpty
    status: Status
    releases: NonEmpty
    criterion: NonEmpty
    delivered: tuple[NonEmpty, ...]
    remaining: tuple[NonEmpty, ...]
    deliveries: tuple[Delivery, ...] = ()

    @model_validator(mode="after")
    def completion_requires_closed_scope(self):
        if self.status == "completed" and (
            self.remaining or any(item.status != "completed" for item in self.deliveries)
        ):
            raise ValueError("completed phase cannot retain unfinished work")
        return self


class ProjectRoadmap(Contract):
    schema_version: Literal["1.0.0"]
    updated_at: NonEmpty
    current_phase: NonEmpty
    current_delivery: NonEmpty
    next_step: NonEmpty
    phases: tuple[Phase, ...]

    @model_validator(mode="after")
    def ordered_unique_phases(self):
        if tuple(phase.id for phase in self.phases) != tuple(str(i) for i in range(8)):
            raise ValueError("roadmap must contain phases 0 through 7 once in order")
        if [phase.id for phase in self.phases if phase.status == "in_progress"] != [
            self.current_phase
        ]:
            raise ValueError("current phase must identify the one active phase")
        return self


def load_project_roadmap(path):
    return ProjectRoadmap.model_validate_json(Path(path).read_bytes())
