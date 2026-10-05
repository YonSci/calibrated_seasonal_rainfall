"""National and fixed JJAS R1+R2 presentation layers for every target.

Smooth only continuous display fields. Summaries use the original grid and the
original forecast/verification eligibility. No model fitting or score selection.
"""
import html
import json
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
from scipy.ndimage import gaussian_filter, map_coordinates, distance_transform_edt
import delivery_map_base as base
from followup_common import area, same_grid, METHOD, freeze_snapshot, unchanged
from verify2026_common import check_forecast
from verify_2026_regimes import inspect_source, make_domains, summarize_domain
from verify2026_outputs import staged_output
from operational_core import read, write, sha, now
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY

VIEWS = {"all_ethiopia": "All Ethiopia",
         "jjas_r12_rainfall_domain": "JJAS R1+R2 rainfall domain"}
DEFINITION = (f"Fixed {REGIME} descriptive domain: cleaned GitHub-refined R1/R2; "
              "JJAS climatological rainfall >=120 mm and >=20% of annual rainfall. "
              "The same domain is used for Jun, Jul, Aug, Sep and JJAS. No onset gate.")
NOTE = ("A presentation and summary domain, not a separate calibration, physical land mask, "
        "monthly rainfall-regime classification, or independently validated EMI zone.")


def load_mask(path, reference):
    with xr.open_dataset(path) as ds:
        mask = ds.load()
    same_grid(mask, reference)
    country_name = "country_mask" if "country_mask" in reference else "region_mask"
    ref = xr.Dataset({"country_mask": reference[country_name]})
    domains = make_domains(mask, ref)
    focused = domains["jjas_r12_rainfall_domain"]
    if not focused.any():
        raise ValueError("Empty R1+R2 rainfall domain")
    if "github_JJAS_noleap_mm" in mask and "github_JJAS_noleap_share" in mask:
        if np.any(focused & ((mask.github_JJAS_noleap_mm.values < 120) |
                             (mask.github_JJAS_noleap_share.values < .20))):
            raise ValueError("Stored domain fails its existing climatological rainfall thresholds")
    return mask, {"all_ethiopia": domains["all_country"], "jjas_r12_rainfall_domain": focused}


def forecast_summary(forecast, fields, domain):
    w = area(forecast)
    country = forecast.region_mask.values == 1
    av = domain & (fields.amount_valid.values == 1)
    pv = domain & (fields.probability_valid.values == 1)
    denom = float(w[domain].sum())
    def avg(z, support):
        return float(np.average(np.asarray(z)[support], weights=w[support])) if support.any() else None
    return {"domain_cells": int(domain.sum()),
            "domain_country_area_percent": float(100 * denom / w[country].sum()),
            "amount_cells": int(av.sum()), "probability_cells": int(pv.sum()),
            "amount_domain_area_percent": float(100*w[av].sum()/denom) if denom else None,
            "probability_domain_area_percent": float(100*w[pv].sum()/denom) if denom else None,
            "mean_rainfall_mm": avg(forecast.corrected_ensemble_mean.values, av),
            "mean_reference_mm": avg(forecast.observed_training_mean.values, av),
            "mean_anomaly_mm": avg(fields.rainfall_anomaly_mm.values, av),
            "mean_local_probabilities": [avg(fields.blend_probability.values[..., k], pv) for k in range(3)],
            "probability_note": "Area mean of local probabilities, not probability of the domain-total rainfall."}


class DisplayGrid:
    """Filter once on country support, then clip the two views identically.

    In particular, selecting the R1+R2 view does NOT refilter boundary values.
    Discrete observed categories are sampled by nearest cell, never interpolated.
    """
    def __init__(self, reference, settings):
        self.settings = settings
        factor = settings["interpolation_factor"]
        lat, lon = np.asarray(reference.lat), np.asarray(reference.lon)
        yi = np.linspace(-.5, len(lat)-.5, len(lat)*factor+1)
        xi = np.linspace(-.5, len(lon)-.5, len(lon)*factor+1)
        self.points = np.array(np.meshgrid(yi, xi, indexing="ij"))
        self.lat = lat[0] + yi*(lat[1]-lat[0])
        self.lon = lon[0] + xi*(lon[1]-lon[0])

    def support(self, mask):
        mask = np.asarray(mask, bool)
        if not mask.any():
            return np.zeros(self.points.shape[1:], bool)
        if mask.all():
            return np.ones(self.points.shape[1:], bool)
        # Padding bounds the signed distance for masks touching a grid edge.
        padded = np.pad(mask, 1, constant_values=False)
        signed = (distance_transform_edt(padded) - distance_transform_edt(~padded))[1:-1, 1:-1]
        return map_coordinates(signed, self.points, order=1, mode="nearest") > 0

    def continuous(self, values, valid):
        values = np.asarray(values, float)
        valid = np.asarray(valid, bool) & np.isfinite(values)
        weights = valid.astype(float)
        data = np.where(valid, values, 0.)
        sigma = self.settings["gaussian_sigma_cells"]
        if sigma:
            data = gaussian_filter(data, sigma, mode="nearest")
            weights = gaussian_filter(weights, sigma, mode="nearest")
        numerator = map_coordinates(data, self.points, order=1, mode="nearest")
        denominator = map_coordinates(weights, self.points, order=1, mode="nearest")
        result = np.divide(numerator, denominator, out=np.full(numerator.shape, np.nan), where=denominator>1e-12)
        result[~self.support(valid)] = np.nan
        return result

    def categorical(self, values, valid):
        values = np.where(valid, values, np.nan).astype(float)
        return map_coordinates(values, self.points, order=0, mode="nearest")


def vector_clip(ax, lines):
    if not lines:
        return
    paths = []
    for x, y in lines:
        points = np.column_stack([x, y])
        if not np.array_equal(points[0], points[-1]):
            points = np.vstack([points, points[0]])
        codes = np.full(len(points), MplPath.LINETO, dtype=np.uint8)
        codes[0], codes[-1] = MplPath.MOVETO, MplPath.CLOSEPOLY
        paths.append(MplPath(points, codes))
    clip = PathPatch(MplPath.make_compound_path(*paths), transform=ax.transData)
    for collection in ax.collections:
        collection.set_clip_path(clip)


def background(ax, grid, country, domain, valid):
    # Outside-focus gray differs from missing-value gray; zero rainfall stays a value.
    for mask, color in [(country, "#edf0f3"), (domain, "#c3c9cf"), (domain & valid, "#ffffff")]:
        if mask.any():
            ax.contourf(grid.lon, grid.lat, np.where(mask, 1., np.nan), levels=[.5,1.5],
                        colors=[color], corner_mask=False)


def finish_axis(ax, grid, lines, domain=None):
    if domain is not None and domain.any() and not domain.all():
        ax.contour(grid.lon, grid.lat, domain.astype(float), levels=[.5], colors="#446761", linewidths=.45)
    vector_clip(ax, lines)
    if lines:
        for x, y in lines:
            ax.plot(x, y, color="#35414b", linewidth=.65, zorder=7)
    ax.set(xlim=(grid.lon[0],grid.lon[-1]), ylim=(grid.lat[0],grid.lat[-1]),
           xlabel="Longitude (°E)", ylabel="Latitude (°N)", aspect="equal")
    ax.grid(alpha=.12, linewidth=.4)


def footer(fig, settings, verification=False):
    text = (f"Display interpolation: {settings['interpolation_factor']}×; Gaussian σ={settings['gaussian_sigma_cells']:g} native cells. "
            "Statistics and exported fields use the original 0.25° grid.\n")
    text += ("Single-year descriptive verification; observed category codes are not smoothed."
             if verification else "Research reconstruction of a May-initialized forecast; not an official EMI/ICPAC product.")
    fig.text(.5, .018, text, ha="center", va="bottom", fontsize=8, color="#48535d")


def save_figure(fig, path, settings):
    fig.savefig(path.with_suffix(".png"), dpi=settings["dpi"], facecolor="white")
    if settings["pdf"]:
        fig.savefig(path.with_suffix(".pdf"), facecolor="white")
    plt.close(fig)


def forecast_maps(forecast, fields, domains, lines, target, out, settings):
    grid = DisplayGrid(forecast, settings)
    country = grid.support(domains["all_ethiopia"])
    pv = fields.probability_valid.values == 1
    av = fields.amount_valid.values == 1
    p = np.stack([grid.continuous(fields.blend_probability.values[..., k], pv) for k in range(3)], -1)
    p = np.clip(p, 0, 1)
    sums = p.sum(-1, keepdims=True)
    p = np.divide(p, sums, out=np.full_like(p, np.nan), where=sums>0)
    pvalid = np.isfinite(p).all(-1) & country
    _, shown, peak, _ = base.classify(p, pvalid, settings["minimum_leading_probability"])
    limit = settings["jjas_anomaly_limit_mm"] if target == "JJAS" else settings["monthly_anomaly_limit_mm"]
    continuous = {
        "rainfall_anomaly_mm": grid.continuous(fields.rainfall_anomaly_mm.values, av),
        "rainfall_anomaly_percent": grid.continuous(fields.rainfall_anomaly_percent.values, av),
        "rainfall_total_mm": grid.continuous(forecast.corrected_ensemble_mean.values, av)}
    total_limit = max(10., float(np.nanquantile(forecast.corrected_ensemble_mean.values[av], .99)))
    for view, domain in domains.items():
        folder = out / view
        folder.mkdir()
        focus = grid.support(domain) & country
        fig = plt.figure(figsize=(10.6, 8.5))
        gs = fig.add_gridspec(3, 2, width_ratios=[17,1], left=.08,right=.86,bottom=.19,top=.83,hspace=.45,wspace=.14)
        ax = fig.add_subplot(gs[:,0])
        background(ax, grid, country, focus, pvalid)
        ax.contourf(grid.lon, grid.lat, np.where(focus & (shown == -1),1.,np.nan), levels=[.5,1.5], colors=["white"], corner_mask=False)
        norm = BoundaryNorm(base.PROB_BOUNDS, 7)
        for row, k in enumerate([2,1,0]):
            cmap = ListedColormap(base.COLORS[k])
            z = np.where(focus & (shown == k),100*peak,np.nan)
            ax.contourf(grid.lon,grid.lat,z,levels=base.PROB_BOUNDS,cmap=cmap,norm=norm,corner_mask=False)
            cax = fig.add_subplot(gs[row,1])
            cb = fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),cax=cax,ticks=[40,50,60,70,80,90,100])
            cb.set_label(["Below normal (%)","Near normal (%)","Above normal (%)"][k])
        finish_axis(ax,grid,lines,focus if view != "all_ethiopia" else None)
        fig.suptitle(f"{target} {YEAR} | rainfall tercile outlook",fontsize=18,y=.965)
        fig.text(.5,.918,f"May initialization · shared probability blend · CHIRPS reference {REF_DASH}",ha="center",fontsize=10)
        fig.text(.5,.883,VIEWS[view]+" · presentation layer",ha="center",fontsize=11,color="#176d62")
        fig.legend(handles=[Patch(facecolor="white",edgecolor="gray",label=f"Weak (<{100*settings['minimum_leading_probability']:g}%) or tied"),
                            Patch(facecolor="#c3c9cf",label="Ineligible in view"),Patch(facecolor="#edf0f3",label="Outside focus")],
                   loc="lower center",bbox_to_anchor=(.5,.09),ncol=3,frameon=False,fontsize=9)
        footer(fig,settings)
        save_figure(fig,folder/"tercile_outlook",settings)
        for key, values in continuous.items():
            percent = key.endswith("percent")
            amount = key == "rainfall_total_mm"
            units = "%" if percent else "mm"
            vmax = total_limit if amount else (100. if percent else limit)
            levels = np.linspace(0,vmax,13) if amount else base.ANOM_STEPS*vmax
            cmap = plt.get_cmap("YlGnBu",12) if amount else ListedColormap(base.ANOM_COLORS)
            norm = BoundaryNorm(levels, cmap.N, clip=False)
            fig, ax = plt.subplots(figsize=(9.4,8.1))
            fig.subplots_adjust(left=.09,right=.87,bottom=.22,top=.83)
            valid = np.isfinite(values)
            background(ax,grid,country,focus,valid)
            z = np.where(focus,values,np.nan)
            im = ax.contourf(grid.lon,grid.lat,z,levels=levels,cmap=cmap,norm=norm,
                             extend="max" if amount else "both",corner_mask=False)
            ticks = np.linspace(0,vmax,5) if amount else np.array([-1,-.6,-.2,0,.2,.6,1])*vmax
            fig.colorbar(im,ax=ax,shrink=.9,ticks=ticks,label=f"Rainfall {'total' if amount else 'anomaly'} ({units})")
            finish_axis(ax,grid,lines,focus if view != "all_ethiopia" else None)
            fig.suptitle(f"{target} {YEAR} | {'corrected mean rainfall' if amount else 'rainfall anomaly'} ({units})",fontsize=17,y=.965)
            fig.text(.5,.918,f"May initialization · corrected ensemble mean · CHIRPS reference {REF_DASH}",ha="center",fontsize=10)
            fig.text(.5,.883,VIEWS[view]+" · presentation layer",ha="center",fontsize=11,color="#176d62")
            message = (f"Percent anomalies hidden where reference rainfall <{settings['percent_anomaly_minimum_climatology_mm']:g} mm."
                       if percent else "Rainfall amount correction; separate from probability calibration.")
            fig.text(.5,.125,message+"\nLight gray: outside focus. Dark gray: ineligible or excluded by the display threshold.",ha="center",fontsize=9)
            footer(fig,settings)
            save_figure(fig,folder/key,settings)


def verification_maps(fields, domains, lines, target, out, settings):
    grid = DisplayGrid(fields, settings)
    country = grid.support(domains["all_ethiopia"])
    av, pv = fields.amount_support.values == 1, fields.probability_support.values == 1
    amount_limit = max(10., float(np.nanquantile(np.abs(np.r_[fields.observed_anomaly_mm.values[av],fields.corrected_mean_anomaly_mm.values[av]]),.98)))
    error_limit = max(1.,float(np.nanquantile(np.abs(fields.corrected_error_mm.values[av]),.98)))
    rps_limit = max(.05,float(np.nanquantile(np.abs(fields.shared_minus_climatology_rps.values[pv]),.98)))
    crps_limit = max(1.,float(np.nanquantile(fields.corrected_crps_mm.values[av],.98)))
    definitions = [
        ("Observed anomaly (mm)","observed_anomaly_mm",av,"BrBG",amount_limit),
        ("Forecast mean anomaly (mm)","corrected_mean_anomaly_mm",av,"BrBG",amount_limit),
        ("Forecast minus observed (mm)","corrected_error_mm",av,"RdBu_r",error_limit),
        ("Observed tercile — native labels","observed_category",pv,None,None),
        ("Shared minus climatology RPS","shared_minus_climatology_rps",pv,"RdBu_r",rps_limit),
        ("Corrected ensemble CRPS (mm)","corrected_crps_mm",av,"viridis",crps_limit)]
    displays = {key: (grid.categorical(fields[key].values,valid) if key=="observed_category" else grid.continuous(fields[key].values,valid))
                for _,key,valid,_,_ in definitions}
    for view, domain in domains.items():
        folder = out/view
        folder.mkdir()
        focus = grid.support(domain) & country
        fig, axes = plt.subplots(2,3,figsize=(15.6,10.6))
        fig.subplots_adjust(left=.055,right=.97,top=.84,bottom=.14,hspace=.29,wspace=.24)
        for ax,(title,key,_,cmap,limit) in zip(axes.flat,definitions):
            z = displays[key]
            background(ax,grid,country,focus,np.isfinite(z))
            if key == "observed_category":
                levels = [-.5,.5,1.5,2.5]
                cmap = ListedColormap(["#c77728","#ece7d9","#278a45"])
                extend = "neither"
            else:
                levels = np.linspace(0,limit,13) if key=="corrected_crps_mm" else np.linspace(-limit,limit,15)
                extend = "max" if key=="corrected_crps_mm" else "both"
            im = ax.contourf(grid.lon,grid.lat,np.where(focus,z,np.nan),levels=levels,cmap=cmap,extend=extend,corner_mask=False)
            cb = fig.colorbar(im,ax=ax,shrink=.83,pad=.025)
            if key=="observed_category":
                cb.set_ticks([0,1,2]);cb.set_ticklabels(["Below","Near","Above"])
            cb.ax.tick_params(labelsize=8)
            finish_axis(ax,grid,lines,focus if view!="all_ethiopia" else None)
            ax.set_title(title,fontsize=10,pad=8)
            ax.tick_params(labelsize=8)
            ax.xaxis.label.set_size(9);ax.yaxis.label.set_size(9)
        fig.suptitle(f"{target} {YEAR} | forecast verification",fontsize=20,y=.97)
        fig.text(.5,.932,f"Frozen May-initialized shared blend · CHIRPS v2 observations · reference {REF_DASH}",ha="center",fontsize=11)
        fig.text(.5,.896,VIEWS[view]+" · presentation layer",ha="center",fontsize=12,color="#176d62")
        fig.text(.5,.079,"Negative RPS difference favors the forecast. Lower CRPS is better. National and domain panels share color scales.\nLight gray: outside focus. Dark gray: no eligible verification data. No observed category is inferred from neighboring cells.",ha="center",fontsize=9)
        footer(fig,settings,verification=True)
        save_figure(fig,folder/"verification_maps",settings)


def build_forecast(source, mask_path, boundary, target, destination, settings):
    hashes = {str(p):sha(p) for p in [source,mask_path,*boundary_files(boundary)]}
    with xr.open_dataset(source) as ds:
        f = ds.load()
    check_forecast(f,target)
    _,domains = load_mask(mask_path,f)
    g = base.derive(f,settings["minimum_leading_probability"],settings["percent_anomaly_minimum_climatology_mm"])
    lines = base.boundary_lines(boundary)
    result = {"kind":"forecast","target":target,"year":YEAR,"created_utc":now(),
              "domain_definition":DEFINITION,"domain_note":NOTE,"source_sha256":hashes,
              "display":settings,"forecast_sha256":sha(source),
              "summaries":{view:forecast_summary(f,g,domain) for view,domain in domains.items()}}
    with staged_output(destination,True) as stage:
        forecast_maps(f,g,domains,lines,target,stage,settings)
        g["jjas_r12_rainfall_domain"] = (("lat","lon"),domains["jjas_r12_rainfall_domain"].astype("int8"))
        g["corrected_ensemble_mean"] = f.corrected_ensemble_mean
        g["observed_training_mean"] = f.observed_training_mean
        g.attrs.update(presentation_domain_definition=DEFINITION,presentation_domain_note=NOTE,
                       forecast_sha256=result["forecast_sha256"],mask_sha256=sha(mask_path),
                       statistics_grid="original 0.25 degree grid; no smoothing",mask_note=NOTE)
        g.to_netcdf(stage/"presentation_fields.nc")
        write(stage/"presentation_summary.json",result)
        if any(sha(Path(p))!=value for p,value in hashes.items()):
            raise ValueError("Input changed during forecast rendering")
    return result


def boundary_files(path):
    return [Path(path).with_suffix(suffix) for suffix in [".shp",".shx",".dbf",".prj"]]


def build_verification(root, mask_path, boundary, target, destination, settings):
    snapshot = freeze_snapshot(root)
    fields,provenance = inspect_source(root,target,snapshot)
    _,domains = load_mask(mask_path,fields)
    mask_digest = sha(mask_path)
    boundary_digests = {str(p):sha(p) for p in boundary_files(boundary)}
    summaries = {view:summarize_domain(fields,domain) for view,domain in domains.items()}
    result = {"kind":"verification","target":target,"year":YEAR,"created_utc":now(),
              "domain_definition":DEFINITION,"domain_note":NOTE,"display":settings,
              "provenance":provenance,"mask_sha256":mask_digest,"boundary_sha256":boundary_digests,
              "frozen_forecasts":snapshot,"summaries":summaries,
              "score_note":"Existing native-grid score fields aggregated on each domain; country scores reproduced. Single year, overlapping targets, no significance or reliability claim."}
    with staged_output(destination,True) as stage:
        verification_maps(fields,domains,base.boundary_lines(boundary),target,stage,settings)
        fields["jjas_r12_rainfall_domain"] = (("lat","lon"),domains["jjas_r12_rainfall_domain"].astype("int8"))
        fields.attrs.update(presentation_domain_definition=DEFINITION,presentation_domain_note=NOTE,
                            mask_sha256=mask_digest,statistics_grid="unchanged native verification fields")
        fields.to_netcdf(stage/"presentation_fields.nc")
        write(stage/"presentation_summary.json",result)
        unchanged(root,snapshot)
        if sha(mask_path)!=mask_digest or any(sha(Path(p))!=v for p,v in boundary_digests.items()):
            raise ValueError("Presentation mask or boundary changed during verification rendering")
    return result


def build_gallery(output, forecast_targets, verified_targets, pending, details):
    """Static, offline gallery. User selects target, product and presentation domain."""
    output = Path(output)
    entries = []
    summary = {"created_utc":now(),"forecast_targets":forecast_targets,"verified_targets":verified_targets,
               "pending_verification_targets":pending,"domain_definition":DEFINITION,"domain_note":NOTE,
               "details":details,"forecasts":[],"verification":[]}
    for kind,targets in [("forecast",forecast_targets),("verification",verified_targets)]:
        for target in targets:
            folder = output/"presentation"/kind/target
            record = read(folder/"presentation_summary.json")
            summary["forecasts" if kind=="forecast" else "verification"].append(record)
            for view,label in VIEWS.items():
                images = ([('tercile_outlook','Leading tercile probability'),('rainfall_total_mm','Corrected mean rainfall'),
                           ('rainfall_anomaly_mm','Rainfall anomaly (mm)'),('rainfall_anomaly_percent','Rainfall anomaly (%)')]
                          if kind=="forecast" else [('verification_maps','Verification maps')])
                entries.append({"kind":kind,"target":target,"view":view,"label":label,
                                "folder":f"presentation/{kind}/{target}/{view}","images":images,
                                "summary":record["summaries"][view],"pdf":record["display"]["pdf"]})
    # Encode '<' to make JSON safe inside a script tag, even if future labels change.
    data = json.dumps(entries,allow_nan=False).replace("<","\\u003c")
    targets = list(dict.fromkeys([*forecast_targets,*verified_targets]))
    buttons = ''.join(f'<option value="{t}">{t}</option>' for t in targets)
    pending_text = html.escape(', '.join(pending) or 'None among requested targets')
    report_link = (' · <a href="'+html.escape(details['verification_report'],quote=True)+'">Consolidated verification report</a>'
                   if details.get('verification_report') else '')
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ethiopia rainfall — forecast and verification views</title><style>
body{{margin:0;background:#edf2f4;color:#20313b;font:16px/1.5 system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:28px}}
header,section{{background:white;border:1px solid #d7e2e7;border-radius:12px;padding:24px;margin-bottom:20px}}h1{{font-size:30px;line-height:1.2}}h2{{font-size:22px}}.tag{{color:#16685f;font-size:13px;letter-spacing:.08em;text-transform:uppercase}}
.note{{background:#f5f8f9;padding:14px;border-left:4px solid #27877a}}.pending{{color:#765321}}label{{display:inline-block;margin:0 20px 15px 0}}select{{display:block;padding:9px;font:inherit;border:1px solid #8aa1ad;border-radius:5px}}a{{color:#06628a}}img{{max-width:100%;height:auto}}figure{{margin:10px 0 28px}}figcaption{{font-weight:600}}table{{border-collapse:collapse;width:100%;margin:15px 0}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #dbe4e9}}.subtle{{font-size:14px;color:#526772}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.wide{{grid-template-columns:1fr}}@media(max-width:750px){{main{{padding:10px}}.grid{{grid-template-columns:1fr}}header,section{{padding:16px}}}}
</style><main><header><div class="tag">May initialization · {YEAR} · research reconstruction</div>
<h1>Ethiopia rainfall forecast and verification</h1><p>National and fixed JJAS R1+R2 rainfall-domain views for each month and the season.</p>
<p class="note">''' + html.escape(DEFINITION + ' ' + NOTE) + '''</p><p class="pending">Pending verification: '''+pending_text+'''. Pending does not mean zero rainfall or zero skill.</p>
<p class="subtle">The forecasts remain frozen. The domain changes only presentation and the area summarized. Continuous map colors are interpolated for display; statistics and NetCDF fields retain the original grid. Not an official EMI/ICPAC product.</p>
<p><a href="presentation_summary.json">Combined summaries and provenance</a> · <a href="state/latest_run.json">Latest run record</a>'''+report_link+'''</p></header>
<section><label>Target<select id="target">'''+buttons+'''</select></label>
<label>Product<select id="kind"><option value="forecast">Forecast</option><option value="verification">Verification</option></select></label>
<label>View<select id="view"><option value="all_ethiopia">All Ethiopia</option><option value="jjas_r12_rainfall_domain">JJAS R1+R2 rainfall domain</option></select></label>
<div id="content"></div></section><noscript>Enable JavaScript to select views, or open the PNG/PDF files in presentation/ directly.</noscript></main>
<script id="data" type="application/json">'''+data+f'''</script><script>
const entries=JSON.parse(document.getElementById('data').textContent);const fmt=(v,n=1)=>v==null?'Unavailable':Number(v).toFixed(n);
function render(){{const t=document.getElementById('target').value,k=document.getElementById('kind').value,v=document.getElementById('view').value;
const e=entries.find(x=>x.target===t&&x.kind===k&&x.view===v),c=document.getElementById('content');
if(!e){{c.innerHTML='<p class="pending">'+t+' '+k+' is not available in this run. Complete observations and verification inputs are required.</p>';return;}}
const s=e.summary;let rows=[['Domain cells',s.domain_cells],['Domain share of country area (%)',fmt(s.domain_country_area_percent)],['Amount coverage within domain (%)',fmt(s.amount_domain_area_percent)],['Probability coverage within domain (%)',fmt(s.probability_domain_area_percent)]];
if(k==='forecast'){{rows.push(['Mean rainfall / reference (mm)',fmt(s.mean_rainfall_mm)+' / '+fmt(s.mean_reference_mm)],['Mean anomaly (mm)',fmt(s.mean_anomaly_mm)],['Area-mean local Below / Near / Above probabilities (%)',s.mean_local_probabilities.map(x=>fmt(x==null?null:100*x)).join(' / ')]);}}
else {{const p=s.probability.shared_blend||{{}},a=s.amount.corrected||{{}};rows.push(['Shared RPS',fmt(p.rps,4)],['Shared RPSS (%)',fmt(p.rpss==null?null:100*p.rpss)],['Corrected CRPS (mm)',fmt(a.crps_mm)],['Corrected CRPSS (%)',fmt(a.crpss==null?null:100*a.crpss)],['Corrected rainfall bias (mm)',fmt(a.bias_mm)]);}}
c.innerHTML='<h2>'+t+' {YEAR} · '+e.label+'</h2><table>'+rows.map(r=>'<tr><th>'+r[0]+'</th><td>'+r[1]+'</td></tr>').join('')+'</table><p class="subtle">'+(k==='forecast'?'Area means of local probabilities are not probabilities for domain-total rainfall.':'Positive skill means improvement over climatology on this support. Single-year results do not establish long-term reliability.')+'</p><p><a href="presentation/'+k+'/'+t+'/presentation_fields.nc">Native fields and domain mask</a> · <a href="presentation/'+k+'/'+t+'/presentation_summary.json">Summary and provenance</a></p><div class="grid '+(k==='verification'?'wide':'')+'">'+e.images.map(x=>'<figure><a href="'+e.folder+'/'+x[0]+'.png"><img loading="lazy" src="'+e.folder+'/'+x[0]+'.png" alt="'+t+' '+e.label+' '+x[1]+'"></a><figcaption>'+x[1]+(e.pdf?' · <a href="'+e.folder+'/'+x[0]+'.pdf">PDF</a>':'')+'</figcaption></figure>').join('')+'</div>';}}
for(const id of ['target','kind','view'])document.getElementById(id).addEventListener('change',render);render();</script></html>'''
    (output/"index.html").write_text(page,encoding="utf-8")
    write(output/"presentation_summary.json",summary)
