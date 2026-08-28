"""Print the catalog and its assumptions.

    python -m aggsim.catalog

Assumptions are printed, never silently applied: the project rule is that an
unsourced value must be visible in program output.
"""

from . import check_pairing, load_catalog


def main() -> None:
    catalog = load_catalog()

    print(f"TRACTORS ({len(catalog.tractors)})")
    for t in catalog.tractors.values():
        print(
            f"  {t.name:24s} L={t.wheelbase.value:.3f} m  "
            f"drawbar={t.drawbar_power.value / 1000:6.1f} kW  ({t.years})"
        )

    print(f"\nIMPLEMENTS ({len(catalog.implements)})")
    for i in catalog.implements.values():
        print(f"  {i.name:44s} {i.type:8s} width={i.working_width.value:6.3f} m")

    print("\nPAIRING FEASIBILITY (drawbar power)")
    for t in catalog.tractors.values():
        feasible = [
            i for i in catalog.implements.values() if check_pairing(t, i).ok
        ]
        widest = max((i.working_width.value for i in feasible), default=0.0)
        print(
            f"  {t.name:24s} {len(feasible)}/{len(catalog.implements)} feasible, "
            f"widest {widest:.3f} m"
        )

    print()
    print(catalog.assumption_report())


if __name__ == "__main__":
    main()
