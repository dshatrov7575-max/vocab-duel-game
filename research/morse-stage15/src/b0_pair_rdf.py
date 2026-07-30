#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

EX = Namespace("urn:morse-stage14:")


def safe_uri(value: str) -> URIRef:
    return URIRef("urn:morse-stage14:item:" + quote(value, safe=""))


def add_profile(graph: Graph, profile: dict[str, Any]) -> URIRef:
    p = safe_uri(profile["profile_id"] + "@" + profile["profile_version"])
    graph.add((p, RDF.type, EX.Profile))
    graph.add((p, EX.profileId, Literal(profile["profile_id"])))
    graph.add((p, EX.profileVersion, Literal(profile["profile_version"])))
    graph.add((p, EX.requiredMappingVersion, Literal(profile["required_mapping_version"])))
    for distinction in profile["supported_distinctions"]:
        graph.add((p, EX.supportsDistinction, Literal(distinction)))
    for idx, (from_state, to_state) in enumerate(profile.get("allowed_special_transitions", []), 1):
        tr = BNode(f"transition-{idx}-{re.sub(r'[^A-Za-z0-9]', '-', from_state)}-{re.sub(r'[^A-Za-z0-9]', '-', to_state)}")
        graph.add((tr, RDF.type, EX.Transition))
        graph.add((tr, EX.fromState, Literal(from_state)))
        graph.add((tr, EX.toState, Literal(to_state)))
        graph.add((p, EX.allowedTransition, tr))
    return p


def add_side(graph: Graph, node: URIRef, side: dict[str, Any]) -> None:
    graph.add((node, RDF.type, EX.Projection))
    graph.add((node, EX.caseId, Literal(side["case_id"])))
    graph.add((node, EX.anchorSha256, Literal(side["anchor_sha256"])))
    graph.add((node, EX.distinctionId, Literal(side["distinction_id"])))
    graph.add((node, EX.mappingVersion, Literal(side["mapping_version"])))
    graph.add((node, EX.projectionKind, Literal(side["projection_kind"])))
    for candidate in side.get("candidates", []):
        graph.add((node, EX.candidate, Literal(candidate)))
    if side.get("special_state") is not None:
        graph.add((node, EX.specialState, Literal(side["special_state"])))


def add_pair(graph: Graph, pair: dict[str, Any], profile_node: URIRef) -> URIRef:
    pair_node = safe_uri(pair["pair_id"])
    source_node = safe_uri(pair["pair_id"] + "::source")
    target_node = safe_uri(pair["pair_id"] + "::target")
    graph.add((pair_node, RDF.type, EX.TransferPair))
    graph.add((pair_node, EX.source, source_node))
    graph.add((pair_node, EX.target, target_node))
    graph.add((pair_node, EX.profile, profile_node))
    graph.add((pair_node, EX.profileVersion, Literal(pair["profile_version"])))
    graph.add((pair_node, EX.changeRecordPresent, Literal(bool(pair["change_record"]["present"]), datatype=XSD.boolean)))
    if pair["change_record"].get("profile_version") is not None:
        graph.add((pair_node, EX.changeRecordProfileVersion, Literal(pair["change_record"]["profile_version"])))
    for candidate in pair.get("allowed_candidates", []):
        graph.add((pair_node, EX.allowedCandidate, Literal(candidate)))
    add_side(graph, source_node, pair["source"])
    add_side(graph, target_node, pair["target"])
    return pair_node


def build_graph(pairs: list[dict[str, Any]], profile: dict[str, Any]) -> Graph:
    graph = Graph()
    graph.bind("ex", EX)
    profile_node = add_profile(graph, profile)
    for pair in pairs:
        add_pair(graph, pair, profile_node)
    return graph
