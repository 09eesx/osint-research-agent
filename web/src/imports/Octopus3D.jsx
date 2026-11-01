import { useEffect, useRef } from "react";
import * as THREE from "three";

// Renk paleti projendeki shadcn temasından türetildi:
// primary (#030213) -> gövde, chart-2 teal -> biyolüminesan aksan
const COLORS = {
  bg: 0x05060d,
  body: 0x1c1d33,
  bodyDark: 0x0e0f1f,
  glow: 0x2dd4bf,
  eye: 0x0a0a12,
  highlight: 0xe8f9f7,
};

export default function Octopus3D() {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    const width = mount.clientWidth;
    const height = mount.clientHeight;

    // --- Sahne kurulumu ---
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(COLORS.bg);
    scene.fog = new THREE.FogExp2(COLORS.bg, 0.045);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 1, 9);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    // --- Işıklar ---
    scene.add(new THREE.AmbientLight(0x334155, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 0.8);
    key.position.set(4, 6, 5);
    scene.add(key);

    const glowLight = new THREE.PointLight(COLORS.glow, 2.2, 8, 2);
    glowLight.position.set(0, 0.6, 1.2);
    scene.add(glowLight);

    // --- Ahtapot kök grubu (kamera sürükleme + yüzme animasyonu için) ---
    const rig = new THREE.Group();
    scene.add(rig);

    const octopus = new THREE.Group();
    rig.add(octopus);

    // Kafa / mantle
    const bodyMat = new THREE.MeshStandardMaterial({
      color: COLORS.body,
      roughness: 0.45,
      metalness: 0.1,
    });
    const head = new THREE.Mesh(new THREE.SphereGeometry(1.15, 32, 32), bodyMat);
    head.scale.set(1, 1.15, 0.95);
    head.position.y = 1.4;
    octopus.add(head);

    // Gözler
    function makeEye(xSign) {
      const eyeGroup = new THREE.Group();
      const socket = new THREE.Mesh(
        new THREE.SphereGeometry(0.24, 16, 16),
        new THREE.MeshStandardMaterial({ color: COLORS.eye, roughness: 0.2 })
      );
      const highlight = new THREE.Mesh(
        new THREE.SphereGeometry(0.07, 8, 8),
        new THREE.MeshBasicMaterial({ color: COLORS.highlight })
      );
      highlight.position.set(0.08, 0.08, 0.2);
      eyeGroup.add(socket, highlight);
      eyeGroup.position.set(xSign * 0.42, 1.55, 0.92);
      return eyeGroup;
    }
    octopus.add(makeEye(1), makeEye(-1));

    // Dokunaçlar: her biri zincirlenmiş segmentlerden oluşan bir grup (prosedürel FK)
    const TENTACLE_COUNT = 8;
    const SEGMENTS = 7;
    const tentacleRoots = [];

    for (let i = 0; i < TENTACLE_COUNT; i++) {
      const angle = (i / TENTACLE_COUNT) * Math.PI * 2;
      const startRadius = 0.85;

      const root = new THREE.Group();
      root.position.set(
        Math.cos(angle) * startRadius,
        0.55,
        Math.sin(angle) * startRadius
      );
      root.rotation.y = -angle;
      octopus.add(root);

      let parent = root;
      const joints = [];
      for (let s = 0; s < SEGMENTS; s++) {
        const t = s / SEGMENTS;
        const radiusTop = 0.16 * (1 - t * 0.7);
        const radiusBottom = 0.16 * (1 - (t + 1 / SEGMENTS) * 0.7);
        const length = 0.55;

        const seg = new THREE.Mesh(
          new THREE.CylinderGeometry(
            Math.max(radiusTop, 0.02),
            Math.max(radiusBottom, 0.015),
            length,
            10
          ),
          bodyMat
        );
        seg.position.y = -length / 2;

        // Her iki segmentte bir küçük emici (sucker) detayı
        if (s % 2 === 0) {
          const sucker = new THREE.Mesh(
            new THREE.TorusGeometry(radiusTop * 0.9, 0.02, 6, 10),
            new THREE.MeshStandardMaterial({ color: COLORS.bodyDark })
          );
          sucker.rotation.x = Math.PI / 2;
          sucker.position.set(0, 0, radiusTop + 0.01);
          seg.add(sucker);
        }

        const jointHolder = new THREE.Group();
        jointHolder.position.copy(parent === root ? root.position.clone().multiplyScalar(0) : new THREE.Vector3());
        jointHolder.add(seg);

        parent.add(jointHolder);
        jointHolder.position.y = s === 0 ? 0 : -length;
        joints.push(jointHolder);
        parent = jointHolder;
      }
      tentacleRoots.push({ root, joints, angle, phase: Math.random() * Math.PI * 2 });
    }

    // --- Kamera sürükleme kontrolü (OrbitControls yerine manuel) ---
    let isDragging = false;
    let prevX = 0;
    let prevY = 0;
    let targetRotY = 0.3;
    let targetRotX = 0.15;
    let rotY = targetRotY;
    let rotX = targetRotX;

    const onPointerDown = (e) => {
      isDragging = true;
      prevX = e.clientX;
      prevY = e.clientY;
    };
    const onPointerUp = () => {
      isDragging = false;
    };
    const onPointerMove = (e) => {
      if (!isDragging) return;
      const dx = e.clientX - prevX;
      const dy = e.clientY - prevY;
      prevX = e.clientX;
      prevY = e.clientY;
      targetRotY += dx * 0.006;
      targetRotX = Math.max(-0.5, Math.min(0.6, targetRotX + dy * 0.004));
    };

    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointermove", onPointerMove);

    // --- Animasyon döngüsü ---
    let raf;
    const clock = new THREE.Clock();

    function animate() {
      const t = clock.getElapsedTime();

      // Otomatik yavaş dönüş (sürüklenmiyorken)
      if (!isDragging) targetRotY += 0.0015;

      rotY += (targetRotY - rotY) * 0.08;
      rotX += (targetRotX - rotX) * 0.08;
      rig.rotation.y = rotY;
      rig.rotation.x = rotX;

      // Yüzme / yüzme hissi veren dikey salınım
      rig.position.y = Math.sin(t * 0.8) * 0.15;

      // Dokunaç dalga hareketi (prosedürel FK)
      tentacleRoots.forEach(({ joints, angle, phase }) => {
        joints.forEach((joint, idx) => {
          const wave = Math.sin(t * 1.6 + phase + idx * 0.6) * (0.18 - idx * 0.012);
          const sway = Math.cos(t * 1.1 + phase + idx * 0.5) * 0.12;
          joint.rotation.x = 0.15 + wave;
          joint.rotation.z = Math.sin(angle) * 0.05 + sway * 0.3;
        });
      });

      // Biyolüminesan ışığın nabız gibi atması
      glowLight.intensity = 1.8 + Math.sin(t * 2) * 0.6;

      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    }
    animate();

    // --- Yeniden boyutlandırma ---
    const onResize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div className="w-full h-full min-h-[480px] rounded-lg overflow-hidden bg-[#05060d]">
      <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />
      <p className="text-center text-xs text-slate-500 mt-[-28px] relative z-10 pointer-events-none">
        Döndürmek için sürükle
      </p>
    </div>
  );
}
