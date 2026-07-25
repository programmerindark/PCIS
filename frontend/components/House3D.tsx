"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

export type House3DProps = {
  fansOn: number;
  installedFans: number;
  padsOn: boolean;
  airSpeed: number | null; // m/s
  risk: string; // Low | Moderate | High
  feelTempC: number | null;
  targetTempC: number | null;
};

const RISK_TINT: Record<string, number> = {
  Low: 0x123b33,
  Moderate: 0x3a2f10,
  High: 0x3a1414,
};
const RISK_COLOR: Record<string, string> = { Low: "#4ade80", Moderate: "#fbbf24", High: "#f87171" };
const H_UNITS = 340;

export default function House3D(props: House3DProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const fanLbl = useRef<HTMLDivElement>(null);
  const padLbl = useRef<HTMLDivElement>(null);
  const flowLbl = useRef<HTMLDivElement>(null);
  const houseLbl = useRef<HTMLDivElement>(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let width = mount.clientWidth || 640;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a1019);
    scene.fog = new THREE.Fog(0x0a1019, 22, 40);

    const camera = new THREE.PerspectiveCamera(40, width / H_UNITS, 0.1, 200);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, H_UNITS);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xbcd6ff, 0x0a1019, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(-6, 12, 9);
    scene.add(key);
    const fill = new THREE.PointLight(0x2dd4bf, 0.5, 40);
    fill.position.set(2, 3, 4);
    scene.add(fill);

    const L = 13, W = 4.2, H = 2.6;

    // floor
    const floor = new THREE.Mesh(
      new THREE.BoxGeometry(L, 0.15, W),
      new THREE.MeshStandardMaterial({ color: 0x0f2233, roughness: 0.95 })
    );
    scene.add(floor);

    // shell + edges + roof
    const shellGeo = new THREE.BoxGeometry(L, H, W);
    const shell = new THREE.Mesh(
      shellGeo,
      new THREE.MeshStandardMaterial({ color: 0x1a2c40, transparent: true, opacity: 0.08, side: THREE.DoubleSide })
    );
    shell.position.y = H / 2;
    scene.add(shell);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(shellGeo),
      new THREE.LineBasicMaterial({ color: 0x3d566f })
    );
    edges.position.y = H / 2;
    scene.add(edges);
    // low gable roof (two slanted translucent planes)
    const roofMat = new THREE.MeshStandardMaterial({ color: 0x24405a, transparent: true, opacity: 0.28, side: THREE.DoubleSide });
    for (const s of [-1, 1]) {
      const p = new THREE.Mesh(new THREE.PlaneGeometry(L, W / 2 + 0.35), roofMat);
      p.position.set(0, H + 0.28, (s * W) / 4);
      p.rotation.x = -Math.PI / 2 + s * 0.34;
      scene.add(p);
    }

    // --- birds (instanced) on the floor --------------------------------
    const birdN = 420;
    const birdGeo = new THREE.SphereGeometry(0.11, 6, 5);
    const birdMesh = new THREE.InstancedMesh(
      birdGeo,
      new THREE.MeshStandardMaterial({ color: 0xd8c39a, roughness: 1 }),
      birdN
    );
    const m = new THREE.Matrix4();
    for (let i = 0; i < birdN; i++) {
      const x = -L / 2 + 1.2 + Math.random() * (L - 2.4);
      const z = (Math.random() - 0.5) * (W - 0.6);
      m.makeScale(1, 0.7, 1.3);
      m.setPosition(x, 0.16, z);
      birdMesh.setMatrixAt(i, m);
    }
    birdMesh.instanceMatrix.needsUpdate = true;
    scene.add(birdMesh);

    // --- fan wall on -X (2 rows) ---------------------------------------
    const nShow = Math.min(Math.max(1, props.installedFans), 8);
    const cols = Math.ceil(nShow / 2);
    const fans: { blades: THREE.Group; disc: THREE.MeshStandardMaterial }[] = [];
    for (let i = 0; i < nShow; i++) {
      const row = i % 2;
      const col = Math.floor(i / 2);
      const g = new THREE.Group();
      const z = (col - (cols - 1) / 2) * (W / cols) * 0.94;
      const y = row === 0 ? H * 0.34 : H * 0.7;
      g.position.set(-L / 2 - 0.06, y, z);

      const housing = new THREE.Mesh(
        new THREE.TorusGeometry(0.46, 0.07, 10, 26),
        new THREE.MeshStandardMaterial({ color: 0x9fb4c9, metalness: 0.4, roughness: 0.5 })
      );
      housing.rotation.y = Math.PI / 2;
      g.add(housing);
      const discMat = new THREE.MeshStandardMaterial({ color: 0x13202e, side: THREE.DoubleSide });
      const disc = new THREE.Mesh(new THREE.CircleGeometry(0.44, 22), discMat);
      disc.rotation.y = Math.PI / 2;
      g.add(disc);
      const blades = new THREE.Group();
      for (let b = 0; b < 5; b++) {
        const holder = new THREE.Group();
        const blade = new THREE.Mesh(
          new THREE.BoxGeometry(0.02, 0.4, 0.13),
          new THREE.MeshStandardMaterial({ color: 0xdfeaf5 })
        );
        blade.position.y = 0.2;
        blade.rotation.z = 0.35;
        holder.add(blade);
        holder.rotation.x = (b / 5) * Math.PI * 2;
        blades.add(holder);
      }
      blades.rotation.y = Math.PI / 2;
      g.add(blades);
      scene.add(g);
      fans.push({ blades, disc: discMat });
    }

    // --- evaporative cooling pad wall on +X (orange slats) -------------
    const padMats: THREE.MeshStandardMaterial[] = [];
    const slats = 7;
    for (let i = 0; i < slats; i++) {
      const mat = new THREE.MeshStandardMaterial({ color: 0x6b4a2a, roughness: 0.9 });
      padMats.push(mat);
      const slat = new THREE.Mesh(new THREE.BoxGeometry(0.16, H * 0.8, (W * 0.92) / slats - 0.03), mat);
      slat.position.set(L / 2 + 0.08, H * 0.45, (i - (slats - 1) / 2) * ((W * 0.92) / slats));
      scene.add(slat);
    }

    // --- airflow arrows (pad -> fans, i.e. toward -X) ------------------
    const arrows: THREE.Mesh[] = [];
    const arrowMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x0e4d66, transparent: true, opacity: 0.9 });
    for (let i = 0; i < 7; i++) {
      const cone = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.5, 8), arrowMat);
      cone.rotation.z = Math.PI / 2; // point -X
      cone.position.set(-L / 2 + Math.random() * L, 0.5 + Math.random() * (H - 1), (Math.random() - 0.5) * (W - 0.8));
      scene.add(cone);
      arrows.push(cone);
    }

    // --- label anchors --------------------------------------------------
    const fanAnchor = new THREE.Vector3(-L / 2, H + 0.5, 0);
    const padAnchor = new THREE.Vector3(L / 2, H + 0.5, 0);
    const flowAnchor = new THREE.Vector3(0, H * 0.62, 0);
    const houseAnchor = new THREE.Vector3(0, H + 0.7, -W / 2);

    const place = (ref: HTMLDivElement | null, a: THREE.Vector3) => {
      if (!ref) return;
      const v = a.clone().project(camera);
      if (v.z > 1) { ref.style.display = "none"; return; }
      ref.style.display = "block";
      ref.style.left = `${(v.x * 0.5 + 0.5) * width}px`;
      ref.style.top = `${(-v.y * 0.5 + 0.5) * H_UNITS}px`;
    };

    let raf = 0;
    const clock = new THREE.Clock();
    let t = 0;
    const animate = () => {
      const dt = Math.min(clock.getDelta(), 0.05);
      t += dt;
      const p = propsRef.current;

      // mostly-front 3/4 camera with gentle sway
      const theta = 0.9 + Math.sin(t * 0.25) * 0.28;
      const R = 17;
      camera.position.set(Math.cos(theta) * R, 8.5, Math.sin(theta) * R);
      camera.lookAt(0, H * 0.35, 0);

      const speed = p.airSpeed && p.airSpeed > 0 ? p.airSpeed : 0.4;
      fans.forEach((f, i) => {
        const active = i < p.fansOn;
        if (active) f.blades.rotation.y += dt * (3 + speed * 1.8);
        f.disc.color.setHex(active ? 0x0e3a44 : 0x13202e);
      });
      padMats.forEach((mm) => mm.color.setHex(p.padsOn ? 0xc2703a : 0x6b4a2a));

      const v = (0.7 + speed * 1.2) * dt;
      const active = p.fansOn > 0;
      arrows.forEach((c) => {
        c.position.x -= active ? v : v * 0.2;
        if (c.position.x < -L / 2 - 0.3) c.position.x = L / 2 + 0.3;
        (c.material as THREE.MeshStandardMaterial).opacity = active ? 0.9 : 0.3;
      });

      (floor.material as THREE.MeshStandardMaterial).color.lerpColors(
        new THREE.Color(0x0f2233), new THREE.Color(RISK_TINT[p.risk] ?? 0x0f2233), 0.5
      );

      place(fanLbl.current, fanAnchor);
      place(padLbl.current, padAnchor);
      place(flowLbl.current, flowAnchor);
      place(houseLbl.current, houseAnchor);

      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };
    animate();

    const onResize = () => {
      width = mount.clientWidth || width;
      renderer.setSize(width, H_UNITS);
      camera.aspect = width / H_UNITS;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, []);

  const p = props;
  return (
    <div style={{ position: "relative", width: "100%", height: H_UNITS }}>
      <div ref={mountRef} style={{ width: "100%", height: H_UNITS }} />
      <Label refEl={fanLbl} title="TUNNEL FANS" value={`${p.fansOn} / ${p.installedFans} ON`} accent="#38bdf8" />
      <Label refEl={padLbl} title="COOLING PADS" value={p.padsOn ? "ON" : "OFF"} accent="#fb923c" />
      <Label refEl={flowLbl} title="AIRFLOW" value={p.airSpeed != null ? `${p.airSpeed.toFixed(2)} m/s` : "—"} accent="#7fd8ff" />
      <Label
        refEl={houseLbl}
        title="HOUSE"
        value={p.feelTempC != null ? `${p.feelTempC.toFixed(1)}°C feels` : (p.targetTempC != null ? `${p.targetTempC.toFixed(1)}°C target` : "—")}
        accent={RISK_COLOR[p.risk] ?? "#e7edf3"}
      />
    </div>
  );
}

function Label({
  refEl, title, value, accent,
}: {
  refEl: React.RefObject<HTMLDivElement>;
  title: string;
  value: string;
  accent: string;
}) {
  return (
    <div
      ref={refEl}
      style={{
        position: "absolute", transform: "translate(-50%, -110%)", pointerEvents: "none",
        display: "none", background: "rgba(10,16,25,0.82)", border: "1px solid #24314a",
        borderRadius: 8, padding: "5px 9px", whiteSpace: "nowrap",
        boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
      }}
    >
      <div style={{ fontSize: 9, letterSpacing: 1, color: "#93a1b5" }}>{title}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: accent }}>{value}</div>
    </div>
  );
}
