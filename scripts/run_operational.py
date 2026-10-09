r"""Run the May-initialized shared-blend production/review stages for one forecast cycle.

Examples (Windows CMD):
  python scripts\run_operational.py --plan
  python scripts\run_operational.py --workflow products
  python scripts\run_operational.py --workflow all
  python scripts\run_operational.py --config config\cycles\sep_2026_ondj.json --workflow products --compare-external --refresh-external

No fitting or regridding is triggered. Existing scientific stages remain authoritative.
The cycle (forecast year, reference period, folders) comes from --config, default
config/operational.json (May 2026). Child stages receive it via CALIBRATION_CYCLE.
See docs/37_NEW_FORECAST_CYCLE.md for a new cycle such as 2027.
"""
import argparse
import os
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
import urllib.error
from operational_core import StageRunner, exclusive_run, read, write, sha, now

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["Jun", "Jul", "Aug", "Sep", "JJAS"]
MONTHS = {"Jun":6,"Jul":7,"Aug":8,"Sep":9}
BASE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/"
# Cycle values; configuration() replaces them with the selected cycle file's values.
YEAR, REF_YEARS, OVERLAP_YEAR = 2026, list(range(1993,2026)), 2025
TAG, SEASON, MONTH_YEAR = "init05", "JJAS", {}


def forecast_file(root, target):
    return Path(root)/f"{TAG}_{target}/{YEAR}/forecast_{YEAR}.nc"


def presentation_mask(cfg):
    """JJAS uses the regime reconciliation mask (R1+R2); other seasons their own rainfall-domain mask."""
    return path(cfg["regime_mask"] if SEASON == "JJAS" else cfg["season_domain_mask"])
PATH_KEYS = ["project_config","forecast_root","verification_root","processed_root","download_cache",
             "regime_mask","boundary","historical_review","output_root"]
PRODUCT_SCRIPTS = ["operational_core.py","presentation_layers.py","run_operational.py",
                   "delivery_map_base.py","delivery_output_runs.py","plot_forecast_products.py",
                   "output_runs.py","cycle.py","common.py","run_monthly.py","followup_common.py",
                   "verify_2026_regimes.py","verify2026_common.py","verify2026_outputs.py"]
EXTERNAL_SCRIPTS = ["external_forecasts.py", "compare_external_forecasts.py", "interpret_external_forecasts.py"]
VERIFY_SCRIPTS = ["prepare_verification_2026.py","verify_frozen_2026.py","verify2026_math.py",
                  "verification_report_core.py","build_verification_report.py"]


def path(value):
    p = Path(value)
    return (p if p.is_absolute() else ROOT/p).resolve()


def require(paths):
    missing = [str(p) for p in paths if not Path(p).is_file()]
    if missing:
        raise ValueError("Missing required files:\n  " + "\n  ".join(missing) +
                         "\nKeep Steps 29-32 installed; see docs/33_OPERATIONAL_RUNNER.md. No file was substituted.")


def configuration(filename, targets=None):
    global YEAR, REF_YEARS, OVERLAP_YEAR, ORDER, MONTHS, TAG, SEASON, MONTH_YEAR
    from cycle import load_cycle, target_window, season_targets
    cycle = load_cycle(filename)          # validates adapter, years and targets
    cfg = read(filename)
    if cfg.get("schema_version")!=1:
        raise ValueError("Unsupported operational configuration schema")
    YEAR, REF_YEARS = cycle.year, cycle.reference_years
    OVERLAP_YEAR = int(cfg.get("overlap_year", 2025))
    # Season profile: months in season order, then the season (e.g. Oct, Nov, Dec, Jan, ONDJ).
    import calendar
    ORDER = season_targets(cycle.project)
    MONTHS = {m: list(calendar.month_abbr).index(m) for m in ORDER[:-1]}
    TAG, SEASON = cycle.tag, cycle.season_name
    MONTH_YEAR = {m: target_window(m, cycle)[0].year for m in MONTHS}
    if SEASON != "JJAS" and "season_domain_mask" not in cfg:
        raise ValueError("Cycles other than JJAS need season_domain_mask (build_season_domain.py --method regime)")
    wanted = targets or cfg["targets"]
    if not wanted or len(set(wanted))!=len(wanted) or not set(wanted)<=set(ORDER):
        raise ValueError("Targets must be unique names among " + ", ".join(ORDER))
    cfg["targets"] = [t for t in ORDER if t in wanted]
    for key in PATH_KEYS + (["season_domain_mask"] if "season_domain_mask" in cfg else []):
        cfg[key] = str(path(cfg[key]))
    settings = cfg["display"]
    if (not isinstance(settings["interpolation_factor"],int) or not 1<=settings["interpolation_factor"]<=20 or
        not 0<=settings["gaussian_sigma_cells"]<=1 or not 1/3<=settings["minimum_leading_probability"]<=1 or
        not 0<=settings["percent_anomaly_minimum_climatology_mm"]<1000 or
        not 1<=settings["monthly_anomaly_limit_mm"]<=5000 or not 1<=settings["jjas_anomaly_limit_mm"]<=10000 or
        not 72<=settings["dpi"]<=300 or type(settings["pdf"]) is not bool):
        raise ValueError("Invalid display configuration")
    ext = cfg.get("external_comparison")
    if ext is not None:
        for key in ["registry","cache_root","output_root"]:
            if key not in ext:
                raise ValueError("external_comparison needs "+key)
        if not path(ext["output_root"]).is_relative_to(path(cfg["output_root"])):
            raise ValueError("external_comparison.output_root must be inside the cycle output_root")
        if ext.get("interpretation_engine","rules")!="rules":
            raise ValueError("Only the deterministic 'rules' interpretation engine is implemented")
    output = path(cfg["output_root"])
    # All operational writes are isolated from input data, prior delivery and science outputs.
    if not output.is_relative_to(ROOT/"outputs") or output==ROOT/"outputs":
        raise ValueError("output_root must be its own subfolder of this project's outputs folder")
    protected = [ROOT/"data",ROOT/"config",ROOT/"scripts",ROOT/"evidence",ROOT/"outputs/forecast_delivery",
                 ROOT/f"outputs/verification_report_{YEAR}",ROOT/"outputs/final_shared_blend"]
    protected += [path(cfg[key]) for key in PATH_KEYS if key!="output_root"]
    for item in protected:
        if item==output or item.is_relative_to(output) or output.is_relative_to(item):
            raise ValueError("Operational output overlaps a protected input/output: " + str(item))
    return cfg


def verification_files(root, target):
    return [root/f"results/{target}/verification_report.json",
            root/f"results/{target}/verification_fields.nc",
            root/f"observations/{target}/chirps_{YEAR}_common.nc"]


def existing_verification(root, targets):
    available = []
    for target in targets:
        files = verification_files(root,target)
        # Observations can exist before scoring. An incomplete result is an error,
        # while observations without any result are simply awaiting verification.
        if any(p.exists() for p in files[:2]):
            require(files)
            available.append(target)
    return available


def probe(url):
    try:
        try:
            response = urllib.request.urlopen(urllib.request.Request(url,method="HEAD"),timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code!=405:
                raise
            response = urllib.request.urlopen(urllib.request.Request(url,headers={"Range":"bytes=0-0"}),timeout=20)
        with response:
            code = response.status
        return {"status":"available" if code in [200,206] else "unknown","http_status":code,"url":url}
    except urllib.error.HTTPError as exc:
        return {"status":"unavailable" if exc.code==404 else "unknown","http_status":exc.code,"url":url}
    except (OSError,urllib.error.URLError) as exc:
        return {"status":"unknown","detail":str(exc),"url":url}


def choose_verification(requested, target_scope, checker=probe):
    explicit = requested != ["auto"]
    wanted = requested if explicit else target_scope
    if not wanted or len(set(wanted))!=len(wanted) or not set(wanted)<=set(ORDER):
        raise ValueError("--verification-targets must be 'auto' alone or target names")
    needed = [m for m in MONTHS if m in wanted or SEASON in wanted]
    records = {m:checker(BASE+f"chirps-v2.0.{MONTH_YEAR.get(m,YEAR)}.{MONTHS[m]:02d}.days_p25.nc") for m in needed}
    for m,r in records.items():
        print("CHIRPS availability:",m,r["status"],flush=True)
    unknown = [m for m,r in records.items() if r["status"]=="unknown"]
    if unknown:
        raise ValueError("Observation availability is unknown for "+", ".join(unknown)+". Check connectivity and retry; network failures are not treated as absent observations. Use --workflow products for an offline presentation run.")
    months = [m for m in needed if records[m]["status"]=="available"]
    ready = [t for t in ORDER if t in wanted and (t in months or (t==SEASON and set(months)==set(MONTHS)))]
    missing = [t for t in wanted if t not in ready]
    if explicit and missing:
        raise ValueError("Requested verification is not ready: "+", ".join(missing)+". Use --verification-targets auto to process the available months.")
    # When the season is ready all its component months are prepared and scored too.
    if SEASON in ready:
        ready = ORDER.copy()
    return months,ready,{"checked_utc":now(),"files":records,"pending":missing,
                         "note":"Availability is not completeness; preparation validates every calendar day, units and reference overlap."}


def preflight(cfg, workflow, verification_request):
    import xarray as xr
    import numpy as np
    from presentation_layers import boundary_files, load_mask
    from followup_common import freeze_snapshot
    from verify2026_common import check_forecast
    from verify_2026_regimes import inspect_source
    import delivery_map_base as base
    packages = {name:importlib.metadata.version(name) for name in
                ["numpy","pandas","xarray","netCDF4","scipy","matplotlib","pyshp","pyproj"]}
    scripts = PRODUCT_SCRIPTS + (VERIFY_SCRIPTS if workflow in ["verify","all"] else [])
    require([ROOT/"scripts"/s for s in scripts])
    mp,bp,vr = path(cfg["regime_mask"]),path(cfg["boundary"]),path(cfg["verification_root"])
    require([mp,presentation_mask(cfg),*boundary_files(bp)])
    lines = base.boundary_lines(bp)
    if not lines:
        raise ValueError("Empty Ethiopia boundary")
    manifest = vr/"frozen_forecasts/freeze_manifest.json"
    snapshot = freeze_snapshot(vr) if manifest.exists() else None
    if workflow in ["verify","all"] and snapshot is None:
        raise ValueError("The existing Step 30 freeze is required before this runner verifies observations. Run prepare_verification_2026.py first; this adapter never replaces or invents a freeze.")
    sources = {}
    reference = None
    for target in cfg["targets"]:
        p = (vr/f"frozen_forecasts/{TAG}_{target}/forecast_{YEAR}.nc" if snapshot else
             forecast_file(path(cfg["forecast_root"]),target))
        require([p])
        with xr.open_dataset(p) as ds:
            d = ds.load()
        check_forecast(d,target)
        load_mask(presentation_mask(cfg),d)
        if reference is not None:
            for key in ["lat","lon","region_mask"]:
                if not np.array_equal(d[key],reference[key]):
                    raise ValueError("Forecast grids or country masks differ between targets")
        reference = d
        sources[target] = p
    existing = existing_verification(vr,cfg["targets"])
    if existing and snapshot is None:
        raise ValueError("Verification results exist without a freeze manifest")
    if workflow == "products":
        if verification_request != ["auto"]:
            if not set(verification_request)<=set(existing):
                raise ValueError("Explicit verification views require complete existing results; use --workflow verify to create them")
            existing = [t for t in ORDER if t in verification_request]
        for t in existing:
            inspect_source(vr,t,snapshot)
        months, ready, availability = [], existing, {"mode":"offline existing verified outputs"}
    else:
        months,ready,availability = choose_verification(verification_request,cfg["targets"])
        require([path(cfg["project_config"])])
        project = read(cfg["project_config"])
        from cycle import load_cycle
        expected = load_cycle(os.environ["CALIBRATION_CYCLE"]).project
        if project.get("initialization_month")!=expected["initialization_month"] or project.get("season")!=expected["season"] or project.get("observation_years")[1]>OVERLAP_YEAR:
            raise ValueError("Project configuration does not match the cycle (initialization month, season, or observation_years ending after the CHIRPS archive year, overlap_year)")
        require([path(project["chirps_file"])])
        # Existing preparation validates all five originals against the freeze.
        require([forecast_file(path(cfg["forecast_root"]),t) for t in ORDER])
        for t in ready:
            folder = path(cfg["processed_root"])/f"{TAG}_{t}"
            require([folder/f"ecmwf_{YEAR}_common.nc",*[folder/f"chirps_{y}_common.nc" for y in REF_YEARS]])
    return {"packages":packages,"sources":sources,"snapshot":snapshot,"existing":existing,
            "months":months,"ready":ready,"availability":availability,"scripts":scripts}


def verify_stages(runner,cfg,info,code_inputs):
    vr = path(cfg["verification_root"])
    ready,months = info["ready"],info["months"]
    if not ready:
        print("WAITING: no requested observation target is available for verification.",flush=True)
        return []
    def command(script,*args):
        return [sys.executable,str(ROOT/"scripts"/script),*map(str,args)]
    config = path(cfg["project_config"])
    historical = path(read(config)["chirps_file"])
    freeze = vr/"frozen_forecasts"
    originals = [forecast_file(path(cfg["forecast_root"]),t) for t in ORDER]
    prepared = [*months, *([SEASON] if set(months)==set(MONTHS) else [])]
    cache_outputs = []
    for m in months:
        for year in [OVERLAP_YEAR,MONTH_YEAR.get(m,YEAR)]:
            f = path(cfg["download_cache"])/f"chirps-v2.0.{year}.{MONTHS[m]:02d}.days_p25.nc"
            cache_outputs.extend([f,f.with_suffix(".download.json")])
    runner.stage("prepare_observations_"+"_".join(months),
                 [*code_inputs,config,historical,freeze,*originals],
                 [*[vr/f"observations/{t}" for t in prepared],*cache_outputs],
                 command=command("prepare_verification_2026.py","--config",config,"--months",*months,
                                 "--input-root",cfg["forecast_root"],"--root",vr,"--cache",cfg["download_cache"],"--regenerate"))
    for target in ready:
        folder = path(cfg["processed_root"])/f"{TAG}_{target}"
        inputs = [*code_inputs,freeze,vr/f"observations/{target}",folder/f"ecmwf_{YEAR}_common.nc",
                  *[folder/f"chirps_{y}_common.nc" for y in REF_YEARS]]
        runner.stage("score_"+target,inputs,[vr/f"results/{target}",vr/f"reports/{target}"],
                     command=command("verify_frozen_2026.py","--root",vr,"--processed-root",cfg["processed_root"],"--targets",target,"--regenerate"))
    return ready


def report_stages(runner,cfg,targets,code_inputs):
    if not targets:
        return None
    vr,out = path(cfg["verification_root"]),path(cfg["output_root"])
    tag = "_".join(targets)
    regime = out/f"regimes/{tag}/regime_verification_summary.json"
    inputs = [*code_inputs,path(cfg["regime_mask"]),presentation_mask(cfg),vr/"frozen_forecasts"]
    for t in targets:
        inputs += verification_files(vr,t)
    runner.stage("regime_summary_"+tag,inputs,[regime.parent],command=[sys.executable,str(ROOT/"scripts/verify_2026_regimes.py"),
                 "--targets",*targets,"--verification-root",str(vr),"--mask",cfg["regime_mask"],"--output-root",str(out/"regimes"),"--regenerate"])
    historical = path(cfg["historical_review"])
    report_inputs = [*inputs,regime]
    for t in targets:
        mp = vr/f"results/{t}/verification_maps.png"
        if mp.is_file():
            report_inputs.append(mp)
    if historical.is_file():
        report_inputs.append(historical)
    runner.stage("verification_report_"+tag,report_inputs,[out/f"reports/{tag}"],command=[sys.executable,str(ROOT/"scripts/build_verification_report.py"),
                 "--targets",*targets,"--verification-root",str(vr),"--regime-summary",str(regime),
                 "--historical-review",str(historical),"--output-root",str(out/"reports"),"--regenerate"])
    return f"reports/{tag}/VERIFICATION_REPORT.html"


def external_stages(runner,cfg,info,refresh):
    """Official outlook comparison: refresh (network, before hashing), prepare, compare, interpret."""
    import external_forecasts as ef
    from compare_external_forecasts import compare
    from interpret_external_forecasts import interpret
    ext = cfg.get("external_comparison")
    if not ext or not ext.get("enabled",True):
        raise ValueError("--compare-external needs an enabled external_comparison block in the cycle file")
    if SEASON not in info["sources"]:
        raise ValueError("--compare-external compares the season target; include "+SEASON+" in the targets")
    registry_path, cache = path(ext["registry"]), ext["cache_root"]
    registry = ef.load_registry(registry_path)
    if refresh:
        # Remote checking happens before any stage hashes its inputs, so a replaced
        # official product at an unchanged URL is never skipped.
        changed = ef.refresh(registry,cache)
        print("External sources changed:",", ".join(changed) or "none",flush=True)
    current = ef.cache_dir(registry,cache)/"current.json"
    if not current.is_file():
        raise ValueError("No official forecast snapshots yet; add --refresh-external")
    snaps = []
    for item in read(current).values():
        snaps += [path(item["file"]),path(item["meta"])]
    out = path(ext["output_root"])
    code = [ROOT/"scripts"/s for s in EXTERNAL_SCRIPTS]
    extractions = path(registry["extractions_dir"])
    native, mask = info["sources"][SEASON], presentation_mask(cfg)
    minimum = cfg["display"]["minimum_leading_probability"]
    runner.stage("external_prepare",[*code,registry_path,current,*snaps,extractions,mask],[out/"sources"],
                 action=lambda:ef.prepare(registry,cache,mask,out/"sources"))
    runner.stage("external_compare",[*code,registry_path,out/"sources",native,mask],[out/"comparison"],
                 settings={"minimum_leading_probability":minimum},
                 action=lambda:compare(out/"sources",native,mask,registry,out/"comparison",minimum))
    runner.stage("external_interpret",[*code,out/"comparison",out/"sources"],[out/"interpretation"],
                 action=lambda:interpret(out/"comparison",out/"sources",out/"interpretation"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config",default="config/operational.json")
    ap.add_argument("--workflow",choices=["products","verify","all"],default="products",
                    help="products: offline views; verify: prepare/score available observations, reports and views; all: verification plus every forecast view")
    ap.add_argument("--targets",nargs="+",help="Override configured target scope (names of the cycle's months and season)")
    ap.add_argument("--verification-targets",nargs="+",default=["auto"],help="'auto' or target names of the cycle")
    ap.add_argument("--plan",action="store_true",help="Preflight and show planned stages without writing project outputs; verify/all checks remote availability")
    ap.add_argument("--force",action="store_true",help="Rebuild derived stages with backups; never refit or replace frozen forecasts")
    ap.add_argument("--resume",action="store_true",help="Content-checked resume is already the default")
    ap.add_argument("--compare-external",action="store_true",help="Compare with official outlooks (cycle external_comparison block)")
    ap.add_argument("--refresh-external",action="store_true",help="Check the official sources online first and keep changed products")
    a = ap.parse_args()
    runner = None
    try:
        # Set before anything imports cycle.py: in-process imports and child stages read this file.
        os.environ["CALIBRATION_CYCLE"] = str(path(a.config))
        cfg = configuration(path(a.config),a.targets)
        # Import after config validation for a more useful error on unsupported cycles.
        from presentation_layers import build_forecast,build_verification,build_gallery,boundary_files
        from followup_common import unchanged
        info = preflight(cfg,a.workflow,a.verification_targets)
        print("Preflight passed. Adapter:",cfg["adapter"],flush=True)
        print("Forecast targets:",", ".join(cfg["targets"]),flush=True)
        print("Verification targets ready:",", ".join(info["ready"]) or "none",flush=True)
        if a.plan:
            stages = (["prepare complete observations","score each available target","regime summary","verification report"] if a.workflow!="products" else [])
            if a.workflow!="verify":
                stages.append("forecast views: national and season rainfall domain for each requested target")
            if a.compare_external:
                stages += [("check official sources online, then " if a.refresh_external else "")+"prepare official outlook records",
                           "compare with the native "+SEASON+" forecast","interpretation and review report"]
            stages += ["verification views: national and season rainfall domain for each ready target","offline gallery and run manifest"]
            for i,item in enumerate(stages,1):
                print(str(i)+".",item)
            print("Output:",cfg["output_root"],"| Read-only plan complete.")
            return
        output = path(cfg["output_root"])
        code_inputs = [ROOT/"scripts"/s for s in info["scripts"]]
        context = {"adapter":cfg["adapter"],"configuration":cfg,"python_version":platform.python_version(),
                   "packages":info["packages"]}
        with exclusive_run(output/"state"):
            runner = StageRunner(ROOT,output/"state",context,a.force)
            write(runner.log_folder/"preflight.json",{"created_utc":now(),"configuration":cfg,
                 "environment":context,"frozen_forecasts":info["snapshot"],"availability":info["availability"]})
            verified = info["ready"] if a.workflow=="products" else verify_stages(runner,cfg,info,code_inputs)
            report = report_stages(runner,cfg,verified,code_inputs) if a.workflow!="products" else None
            vr = path(cfg["verification_root"])
            common = [*code_inputs,presentation_mask(cfg),*boundary_files(path(cfg["boundary"]))]
            if info["snapshot"]:
                common.append(vr/"frozen_forecasts")
            forecasts = []
            if a.workflow!="verify":
                for target,source in info["sources"].items():
                    dest = output/f"presentation/forecast/{target}"
                    runner.stage("forecast_view_"+target,[*common,source],[dest],
                                 action=lambda s=source,t=target,o=dest:build_forecast(s,presentation_mask(cfg),path(cfg["boundary"]),t,o,cfg["display"]))
                    forecasts.append(target)
            for target in verified:
                dest = output/f"presentation/verification/{target}"
                runner.stage("verification_view_"+target,[*common,*verification_files(vr,target)],[dest],
                             action=lambda t=target,o=dest:build_verification(vr,presentation_mask(cfg),path(cfg["boundary"]),t,o,cfg["display"]))
            comparison = external_stages(runner,cfg,info,a.refresh_external) if a.compare_external else None
            pending = [t for t in cfg["targets"] if t not in verified]
            gallery_inputs = [*common]
            if comparison:
                gallery_inputs.append(comparison/"interpretation")
            for kind,targets in [("forecast",forecasts),("verification",verified)]:
                gallery_inputs += [output/f"presentation/{kind}/{t}" for t in targets]
            details = {"workflow":a.workflow,"forecast_status":"retrospective reconstruction", "verification_report":report,
                       **({"external_comparison_report":str((comparison/"interpretation/report.html").relative_to(output)).replace("\\","/")} if comparison else {}),
                       "complete_requested_verification":not pending,
                       **({"full_jjas_verified":"JJAS" in verified} if SEASON=="JJAS" else {"full_season_verified":SEASON in verified})}
            runner.stage("gallery",gallery_inputs,[output/"index.html",output/"presentation_summary.json"],
                         settings={"forecast_targets":forecasts,"verified_targets":verified,"pending":pending,"details":details},
                         action=lambda:build_gallery(output,forecasts,verified,pending,details))
            if info["snapshot"]:
                unchanged(vr,info["snapshot"])
            runner.finish("completed_with_pending_verification" if pending else "completed",pending_verification=pending,
                          verified_targets=verified,forecast_targets=forecasts,gallery=str(output/"index.html"))
            print("Ready:",output/"index.html",flush=True)
            if pending:
                print("Pending verification:",", ".join(pending),"| Forecasts remain unchanged.",flush=True)
    except (ValueError,KeyError,OSError,ImportError,subprocess.CalledProcessError) as exc:
        if runner and runner.record["status"] not in ["failed","completed","completed_with_pending_verification"]:
            runner.finish("failed",error=str(exc))
        print("ERROR:",exc,file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if runner:
            runner.finish("interrupted")
        print("Interrupted. Rerun the same command to resume completed stages.",file=sys.stderr)
        return 130
    return 0


if __name__=="__main__":
    sys.exit(main())
