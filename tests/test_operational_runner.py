"""Meaningful runner/presentation tests. All fixtures here are synthetic.

Run from the existing project after installing Steps 29-33:
  python -m unittest discover -s tests -p test_operational_runner.py -v
No real project output, input, forecast or observation is changed by these tests.
"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import xarray as xr
import shapefile
from pyproj import CRS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import operational_core as core
import run_operational as ops
import presentation_layers as layers
from followup_common import freeze_snapshot, METHOD
from verify2026_common import PERIODS
from verify_frozen_2026 import calculate


def fixture(target):
    factor = 4 if target=="JJAS" else 1
    base = np.arange(20).reshape(4,5)*2.
    history = factor*(np.arange(30,96,2)[:,None,None]+base)
    corrected = np.repeat((factor*(50+base))[None],51,axis=0)
    q1,q2 = np.quantile(history,[1/3,2/3],axis=0)
    p = np.zeros((4,5,3));p[...,0]=1
    smooth = (51*p+.5)/52.5
    clim = np.full_like(p,1/3)
    f = xr.Dataset(coords={"lat":7.125+.25*np.arange(4),"lon":37.125+.25*np.arange(5),
                           "member":np.arange(51),"category":["below","near","above"]},
        attrs={"initialization_month":5,"target_year":2026,"target_period":json.dumps({"name":target,"start":PERIODS[target][0],"end":PERIODS[target][1]}),
               "training_years":"1993-2025","method":"shared climatology blend","climatology_weight":.5})
    f["precip_corrected"] = (("member","lat","lon"),corrected)
    for key,z in [("corrected_ensemble_mean",corrected.mean(0)),("observed_training_mean",history.mean(0)),
                  ("corrected_mean_anomaly",corrected.mean(0)-history.mean(0)),("q1",q1),("q2",q2)]:
        f[key]=(("lat","lon"),z)
    for key in ["precip_corrected","corrected_ensemble_mean","observed_training_mean","corrected_mean_anomaly","q1","q2"]:
        f[key].attrs["units"]="mm"
    for key,z in [("base_probability",p),("smoothed_probability",smooth),("climatology_probability",clim),("blend_probability",.5*smooth+.5*clim)]:
        f[key]=(("lat","lon","category"),z)
    country=np.ones((4,5),"int8");country[-1,-1]=0
    for key in ["region_mask","amount_eligible","probability_eligible"]:
        f[key]=(("lat","lon"),country)
    observed=factor*(50+base)
    observed[1,2]+=10*factor;observed[2,3]+=40*factor
    return f,history,corrected-5*factor,observed


def project_fixture(root):
    """A tiny project, all 5 forecasts, 3 verified months, official-shaped cache."""
    root=Path(root)
    (root/"scripts").mkdir(parents=True)
    for name in set(ops.PRODUCT_SCRIPTS+ops.VERIFY_SCRIPTS):
        shutil.copy2(ROOT/"scripts"/name,root/"scripts"/name)
    vr=root/"outputs/verification_2026"
    manifest={"evaluation_year":2026,"training_years":"1993-2025","targets":{}}
    for target in ops.ORDER:
        f,h,raw,obs=fixture(target)
        source=root/f"outputs/final_shared_blend/init05_{target}/2026/forecast_2026.nc"
        source.parent.mkdir(parents=True)
        f.to_netcdf(source)
        frozen=vr/f"frozen_forecasts/init05_{target}/forecast_2026.nc"
        frozen.parent.mkdir(parents=True)
        shutil.copy2(source,frozen)
        manifest["targets"][target]={"source":str(source),"sha256":core.sha(source)}
        processed=root/f"data/processed/init05_{target}"
        processed.mkdir(parents=True)
        r=xr.Dataset({"precip_season":(("member","lat","lon"),raw)},coords={"member":f.member,"lat":f.lat,"lon":f.lon},
                     attrs={"season_start":"2026-"+PERIODS[target][0],"season_end":"2026-"+PERIODS[target][1]})
        r.precip_season.attrs["units"]="mm";r.to_netcdf(processed/"ecmwf_2026_common.nc")
        for i,year in enumerate(range(1993,2026)):
            d=xr.Dataset({"precip_season":(("year","lat","lon"),h[i][None])},coords={"year":[year],"lat":f.lat,"lon":f.lon},
                         attrs={"config_json":json.dumps({"season":{"name":target,"start":PERIODS[target][0],"end":PERIODS[target][1]}})})
            d.precip_season.attrs["units"]="mm";d.to_netcdf(processed/f"chirps_{year}_common.nc")
    core.write(vr/"frozen_forecasts/freeze_manifest.json",manifest)
    for target in ["Jun","Jul","Aug"]:
        f,h,raw,obs=fixture(target)
        report,fields=calculate(f,raw,h,obs);fields.attrs["target"]=target
        folder=vr/f"results/{target}";folder.mkdir(parents=True)
        fields.to_netcdf(folder/"verification_fields.nc")
        op=vr/f"observations/{target}/chirps_2026_common.nc";op.parent.mkdir(parents=True)
        xr.Dataset({"precip_season":(("lat","lon"),obs)},coords={"lat":f.lat,"lon":f.lon}).to_netcdf(op)
        report.update(target=target,year=2026,forecast_sha256=manifest["targets"][target]["sha256"],observations_sha256=core.sha(op))
        core.write(folder/"verification_report.json",report)
    f,h,raw,obs=fixture("Jun")
    mask=xr.Dataset(coords={"lat":f.lat,"lon":f.lon},attrs={"method":METHOD,"training_years":json.dumps(list(range(1993,2026)))})
    codes=np.tile([1,2,3,3,0],(4,1));codes[-1,-1]=-2
    mask["region_mask"]=f.region_mask
    mask["github_regime_cleaned"]=(("lat","lon"),codes.astype("int8"))
    mask["github_jjas_r12_rainfall_cleaned"]=(("lat","lon"),np.isin(codes,[1,2]).astype("int8"))
    mp=root/"evidence/followup_regime_comparison_and_masks.nc";mp.parent.mkdir();mask.to_netcdf(mp)
    boundary=root/"data/boundaries/ethiopia/eth_admin0.shp";boundary.parent.mkdir(parents=True)
    with shapefile.Writer(str(boundary)) as writer:
        writer.field("name","C");writer.poly([[[37.,7.],[37.,8.],[38.25,8.],[38.25,7.],[37.,7.]]]);writer.record("SYNTHETIC")
    boundary.with_suffix(".prj").write_text(CRS.from_epsg(4326).to_wkt())
    cfg=core.read(ROOT/"config/operational.json")
    cfg["display"].update(interpolation_factor=2,gaussian_sigma_cells=.3,dpi=72,pdf=False)
    core.write(root/"config/operational.json",cfg)
    historical=root/"data/raw/chirps/synthetic_history.nc"
    core.write(root/"config/project.json",{"initialization_month":5,"season":{"name":"JJAS","start":"06-01","end":"09-30"},
                "observation_years":[1993,2025],"chirps_file":str(historical),"chirps_variable":"precip"})
    daily_old=[]
    for name,month in ops.MONTHS.items():
        for year in [2025,2026]:
            times=pd.date_range(f"{year}-{PERIODS[name][0]}",f"{year}-{PERIODS[name][1]}")
            values=np.repeat(((h[-1] if year==2025 else obs)/len(times))[None],len(times),axis=0)
            daily=xr.Dataset({"precip":(("time","lat","lon"),values)},coords={"time":times,"lat":f.lat,"lon":f.lon},
                             attrs={"title":"SYNTHETIC TEST CHIRPS Version 2.0","version":"2.0"})
            daily.precip.attrs["units"]="mm/day"
            cache=root/"data/raw/chirps/verification_p25"/f"chirps-v2.0.{year}.{month:02d}.days_p25.nc"
            cache.parent.mkdir(parents=True,exist_ok=True);daily.to_netcdf(cache)
            core.write(cache.with_suffix(".download.json"),{"url":ops.BASE+cache.name,"sha256":core.sha(cache),"test_fixture":True})
            if year==2025:daily_old.append(daily)
    xr.concat(daily_old,dim="time").to_netcdf(historical)
    return vr


class OperationalTests(unittest.TestCase):
    def test_resume_tampering_failure_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"input";source.write_text("a");dest=root/"output"
            calls=[]
            def action():calls.append(1);dest.write_text(source.read_text())
            with core.exclusive_run(root/"state"):
                with self.assertRaisesRegex(ValueError,"lock exists"):
                    with core.exclusive_run(root/"state"):pass
                r=core.StageRunner(root,root/"state",{"version":1})
                r.stage("copy",[source],[dest],action=action)
                r.stage("copy",[source],[dest],action=action)
                self.assertEqual(len(calls),1)
                dest.write_text("tampered");r.stage("copy",[source],[dest],action=action)
                source.write_text("b");r.stage("copy",[source],[dest],action=action)
                self.assertEqual(len(calls),3)
                with self.assertRaises(subprocess.CalledProcessError):
                    r.stage("fail",[source],[root/"missing"],command=[sys.executable,"-c","raise SystemExit(7)"])
                self.assertEqual(r.record["status"],"failed")
                self.assertFalse((root/"state/stages/fail.json").exists())
            self.assertFalse((root/"state/RUNNING.lock").exists())

    def test_availability_and_scope(self):
        def checker(url):return {"status":"unavailable" if ".09." in url or url.startswith(ops.ANNUAL_BASE+"chirps") else "available","url":url}
        months,ready,r=ops.choose_verification(["auto"],ops.ORDER,checker)
        self.assertEqual(ready,["Jun","Jul","Aug"])
        self.assertEqual(r["pending"],["Sep","JJAS"])
        # A by_month file not published, but the annual file is: the month is taken from the annual file
        def annual(url):return {"status":"unavailable" if ".09." in url else "available","url":url}
        months,ready,r=ops.choose_verification(["auto"],ops.ORDER,annual)
        self.assertEqual(ready,ops.ORDER)
        self.assertEqual(r["files"]["Sep"]["url"],ops.ANNUAL_BASE+f"chirps-v2.0.{ops.YEAR}.days_p25.nc")
        self.assertEqual(r["files"]["Sep"]["by_month"]["status"],"unavailable")
        with self.assertRaisesRegex(ValueError,"not ready"):
            ops.choose_verification(["JJAS"],ops.ORDER,checker)
        with self.assertRaisesRegex(ValueError,"unknown"):
            ops.choose_verification(["auto"],ops.ORDER,lambda url:{"status":"unknown"})
        self.assertEqual(ops.choose_verification(["auto"],ops.ORDER,lambda url:{"status":"available"})[1],ops.ORDER)

    def test_fixed_domain_and_no_category_interpolation(self):
        f,h,raw,obs=fixture("Jun")
        settings=core.read(ROOT/"config/operational.json")["display"]
        settings.update(interpolation_factor=4)
        grid=layers.DisplayGrid(f,settings)
        labels=np.tile([0,1,2,1,0],(4,1))
        z=grid.categorical(labels,f.region_mask.values==1)
        self.assertTrue(set(np.unique(z[np.isfinite(z)]))<={0.,1.,2.})
        values=np.full((4,5),17.)
        a=grid.continuous(values,f.region_mask.values==1)
        np.testing.assert_allclose(a[np.isfinite(a)],17.)
        with tempfile.TemporaryDirectory() as tmp:
            vr=project_fixture(Path(tmp))
            mp=Path(tmp)/"evidence/followup_regime_comparison_and_masks.nc"
            for target in ops.ORDER:
                forecast=fixture(target)[0]
                _,domains=layers.load_mask(mp,forecast)
                self.assertEqual(int(domains["jjas_r12_rainfall_domain"].sum()),8)
            with xr.open_dataset(mp) as ds:m=ds.load()
            m.attrs["training_years"]=json.dumps(list(range(1993,2027)));m.to_netcdf(mp)
            with self.assertRaisesRegex(ValueError,"baseline"):
                layers.load_mask(mp,f)

    def test_cli_products_resume_and_native_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vr=project_fixture(root)
            snapshot=freeze_snapshot(vr)
            command=[sys.executable,str(root/"scripts/run_operational.py"),"--workflow","products"]
            plan=subprocess.run(command+["--plan"],capture_output=True,text=True)
            self.assertEqual(plan.returncode,0,plan.stdout+plan.stderr)
            self.assertFalse((root/"outputs/operational_2026").exists())
            run=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            out=root/"outputs/operational_2026"
            result=core.read(out/"presentation_summary.json")
            self.assertEqual(result["forecast_targets"],ops.ORDER)
            self.assertEqual(result["verified_targets"],["Jun","Jul","Aug"])
            self.assertEqual(result["pending_verification_targets"],["Sep","JJAS"])
            self.assertEqual(snapshot,freeze_snapshot(vr))
            with xr.open_dataset(out/"presentation/forecast/Jun/presentation_fields.nc") as g:
                f=fixture("Jun")[0]
                pv=f.region_mask.values==1
                np.testing.assert_array_equal(g.blend_probability.values[pv],f.blend_probability.values[pv])
            with xr.open_dataset(out/"presentation/verification/Jun/presentation_fields.nc") as exported,xr.open_dataset(vr/"results/Jun/verification_fields.nc") as original:
                for key in original.data_vars:
                    np.testing.assert_array_equal(exported[key].values,original[key].values)
            again=subprocess.run(command+["--resume"],capture_output=True,text=True)
            self.assertEqual(again.returncode,0,again.stdout+again.stderr)
            self.assertTrue(all(s["status"]=="reused" for s in core.read(out/"state/latest_run.json")["stages"]))
            self.assertFalse(list((out/"presentation/forecast").glob("*_backup_*")))

    def test_complete_verification_adapter_with_cached_synthetic_days(self):
        """Real preparation/scoring/report commands; no network. Rendering already tested above."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();vr=project_fixture(root)  # resolve: CI temp paths use 8.3 short names
            before=freeze_snapshot(vr)
            # Running these functions in process lets availability be an explicit mock;
            # every scientific stage still runs the real CLI in the temporary project.
            with patch.object(ops,"ROOT",root):
                cfg=ops.configuration(root/"config/operational.json")
                info={"ready":ops.ORDER,"months":list(ops.MONTHS)}
                runner=core.StageRunner(root,root/"outputs/operational_2026/state",{"synthetic_test":True})
                inputs=[root/"scripts"/s for s in set(ops.PRODUCT_SCRIPTS+ops.VERIFY_SCRIPTS)]
                ready=ops.verify_stages(runner,cfg,info,inputs)
                link=ops.report_stages(runner,cfg,ready,inputs)
                self.assertTrue((root/"outputs/operational_2026"/link).is_file())
                self.assertTrue(core.read(root/"outputs/operational_2026/reports/Jun_Jul_Aug_Sep_JJAS/report_summary.json")["full_JJAS_verified"])
                with xr.open_dataset(vr/"observations/JJAS/chirps_2026_common.nc") as seasonal:
                    self.assertEqual(seasonal.attrs["expected_days"],122)
                    np.testing.assert_allclose(seasonal.precip_season,fixture("JJAS")[3])
                self.assertEqual(before,freeze_snapshot(vr))
                n=len(runner.record["stages"])
                ops.verify_stages(runner,cfg,info,inputs)
                ops.report_stages(runner,cfg,ready,inputs)
                self.assertTrue(all(s["status"]=="reused" for s in runner.record["stages"][n:]))


if __name__=="__main__":
    unittest.main(verbosity=2)
