"""CLI entry point — KRI/KPI context builder for TM narrative generation.

Usage: python main.py --country PL --business-line RB --ingestion-quarter Q1_2026
"""
import argparse, time, sys

from core import resolve_quarter, load_tables, filter_kris, enrich_kpis, build_output


def main():
    ap = argparse.ArgumentParser(description="Build LLM context from TM KRI/KPI data.")
    ap.add_argument("--country", required=True, help="2-letter country code (e.g. PL, RO, FR)")
    ap.add_argument("--business-line", required=True, help="Business line (e.g. RB, WB)")
    ap.add_argument("--ingestion-quarter", required=True, help="Ingestion quarter (e.g. Q1_2026)")
    ap.add_argument("--input-dir", default="input/", help="Directory containing Excel workbooks (default: input/)")
    ap.add_argument("--output-dir", default="output/", help="Directory for generated JSON files (default: output/)")
    args = ap.parse_args()
    t0 = time.perf_counter()

    # Quarter resolution
    qi = resolve_quarter(args.ingestion_quarter)
    print(f"[Quarters] ingestion={qi.ingestion}  test={qi.test}  base={qi.base}")

    # Load
    tables = load_tables(args.input_dir, args.country, args.business_line)
    if not tables:
        print("[ERROR] No tables loaded.", file=sys.stderr); sys.exit(1)

    # Filter KRIs
    print("[KRI Filtering]")
    kri_results = filter_kris(tables, qi)
    ads = set(kri_results)
    print(f"  → {len(ads)} alert definition(s) with triggered KRI(s)\n")

    # Enrich KPIs
    print("[KPI Enrichment]")
    kpi_data, kpi_avail = enrich_kpis(tables, ads, qi)

    # Build output
    print("\n[Building output]")
    build_output(kri_results, kpi_data, kpi_avail, qi, args.output_dir,
                 args.country, args.business_line)

    print(f"\n[Done] {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
