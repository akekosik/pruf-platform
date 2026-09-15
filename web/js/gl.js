/* ============================================================================
   ПРУФ · 3D-сцена на чистом WebGL, без библиотек и без CDN.
   Полигональные тела (икосаэдр, тор, октаэдр) + каркас + светящееся ядро.
   Если WebGL недоступен — контейнер получает класс no-gl и работает CSS-замена.
   ============================================================================ */
(function () {
	"use strict"

	/* ------------------------------------------------------------- матрицы */
	function mIdent() {
		return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
	}
	function mPerspective(fovy, aspect, near, far) {
		var f = 1 / Math.tan(fovy / 2),
			nf = 1 / (near - far)
		return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0])
	}
	function mMul(a, b) {
		var o = new Float32Array(16)
		for (var i = 0; i < 4; i++) {
			for (var j = 0; j < 4; j++) {
				var s = 0
				for (var k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]
				o[i * 4 + j] = s
			}
		}
		return o
	}
	function mTranslate(x, y, z) {
		var m = mIdent()
		m[12] = x
		m[13] = y
		m[14] = z
		return m
	}
	function mScale(s) {
		var m = mIdent()
		m[0] = m[5] = m[10] = s
		return m
	}
	function mRotX(a) {
		var c = Math.cos(a),
			s = Math.sin(a),
			m = mIdent()
		m[5] = c
		m[6] = s
		m[9] = -s
		m[10] = c
		return m
	}
	function mRotY(a) {
		var c = Math.cos(a),
			s = Math.sin(a),
			m = mIdent()
		m[0] = c
		m[2] = -s
		m[8] = s
		m[10] = c
		return m
	}
	function mRotZ(a) {
		var c = Math.cos(a),
			s = Math.sin(a),
			m = mIdent()
		m[0] = c
		m[1] = s
		m[4] = -s
		m[5] = c
		return m
	}
	function mNormal3(m) {
		/* для равномерного масштаба достаточно верхнего блока 3x3 */
		return new Float32Array([m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]])
	}

	/* ----------------------------------------------------------- геометрия */
	function icosahedron() {
		var t = (1 + Math.sqrt(5)) / 2
		var v = [
			[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
			[0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
			[t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
		]
		var f = [
			[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
			[1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
			[3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
			[4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
		]
		return { verts: v.map(norm3), faces: f }
	}
	function norm3(p) {
		var l = Math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]) || 1
		return [p[0] / l, p[1] / l, p[2] / l]
	}
	function subdivide(geo, times) {
		for (var t = 0; t < times; t++) {
			var verts = geo.verts.slice(),
				faces = [],
				cache = {}
			function mid(a, b) {
				var key = Math.min(a, b) + "_" + Math.max(a, b)
				if (cache[key] !== undefined) return cache[key]
				var pa = verts[a],
					pb = verts[b]
				verts.push(norm3([pa[0] + pb[0], pa[1] + pb[1], pa[2] + pb[2]]))
				cache[key] = verts.length - 1
				return cache[key]
			}
			for (var i = 0; i < geo.faces.length; i++) {
				var f = geo.faces[i],
					a = mid(f[0], f[1]),
					b = mid(f[1], f[2]),
					c = mid(f[2], f[0])
				faces.push([f[0], a, c], [f[1], b, a], [f[2], c, b], [a, b, c])
			}
			geo = { verts: verts, faces: faces }
		}
		return geo
	}
	function sphereMesh(sub) {
		var geo = subdivide(icosahedron(), sub)
		var pos = [],
			nor = []
		for (var i = 0; i < geo.faces.length; i++) {
			var f = geo.faces[i]
			for (var k = 0; k < 3; k++) {
				var p = geo.verts[f[k]]
				pos.push(p[0], p[1], p[2])
				nor.push(p[0], p[1], p[2])
			}
		}
		return { pos: pos, nor: nor, edges: edgesOf(geo) }
	}
	function edgesOf(geo) {
		var seen = {},
			out = []
		for (var i = 0; i < geo.faces.length; i++) {
			var f = geo.faces[i]
			for (var k = 0; k < 3; k++) {
				var a = f[k],
					b = f[(k + 1) % 3],
					key = Math.min(a, b) + "_" + Math.max(a, b)
				if (seen[key]) continue
				seen[key] = 1
				var pa = geo.verts[a],
					pb = geo.verts[b]
				out.push(pa[0], pa[1], pa[2], pb[0], pb[1], pb[2])
			}
		}
		return out
	}
	function torusMesh(R, r, seg, ring) {
		var pos = [],
			nor = []
		function pt(i, j) {
			var u = (i / seg) * Math.PI * 2,
				v = (j / ring) * Math.PI * 2
			var cu = Math.cos(u),
				su = Math.sin(u),
				cv = Math.cos(v),
				sv = Math.sin(v)
			return { p: [(R + r * cv) * cu, (R + r * cv) * su, r * sv], n: [cv * cu, cv * su, sv] }
		}
		for (var i = 0; i < seg; i++) {
			for (var j = 0; j < ring; j++) {
				var a = pt(i, j),
					b = pt(i + 1, j),
					c = pt(i + 1, j + 1),
					d = pt(i, j + 1)
				var tri = [a, b, c, a, c, d]
				for (var k = 0; k < 6; k++) {
					pos.push(tri[k].p[0], tri[k].p[1], tri[k].p[2])
					nor.push(tri[k].n[0], tri[k].n[1], tri[k].n[2])
				}
			}
		}
		return { pos: pos, nor: nor, edges: [] }
	}

	/* ------------------------------------------------------------- шейдеры */
	var VS_SOLID = [
		"attribute vec3 aPos; attribute vec3 aNor;",
		"uniform mat4 uProj; uniform mat4 uModel; uniform mat3 uNormal;",
		"varying vec3 vNor; varying vec3 vPos;",
		"void main(){ vec4 wp = uModel * vec4(aPos,1.0); vPos = wp.xyz;",
		"  vNor = normalize(uNormal * aNor); gl_Position = uProj * wp; }",
	].join("\n")
	var FS_SOLID = [
		"precision mediump float;",
		"varying vec3 vNor; varying vec3 vPos;",
		"uniform vec3 uColor; uniform vec3 uColor2; uniform float uAlpha;",
		"void main(){",
		"  vec3 N = normalize(vNor);",
		"  vec3 V = normalize(-vPos);",
		"  vec3 L1 = normalize(vec3(0.6, 0.9, 0.8));",
		"  vec3 L2 = normalize(vec3(-0.8, -0.3, 0.5));",
		"  float d1 = max(dot(N, L1), 0.0);",
		"  float d2 = max(dot(N, L2), 0.0);",
		"  float rim = pow(1.0 - max(dot(N, V), 0.0), 2.4);",
		"  vec3 col = uColor * (0.22 + 0.78 * d1) + uColor2 * (0.42 * d2);",
		"  vec3 spec = vec3(1.0) * pow(max(dot(reflect(-L1, N), V), 0.0), 22.0) * 0.5;",
		"  col += spec + uColor2 * rim * 0.95;",
		"  gl_FragColor = vec4(col, uAlpha);",
		"}",
	].join("\n")
	var VS_LINE = [
		"attribute vec3 aPos;",
		"uniform mat4 uProj; uniform mat4 uModel;",
		"varying float vD;",
		"void main(){ vec4 wp = uModel * vec4(aPos,1.0); vD = wp.z; gl_Position = uProj * wp; }",
	].join("\n")
	var FS_LINE = [
		"precision mediump float;",
		"varying float vD;",
		"uniform vec3 uColor; uniform float uAlpha;",
		"void main(){ float f = clamp((vD + 5.0) / 6.0, 0.25, 1.0);",
		"  gl_FragColor = vec4(uColor * f, uAlpha * f); }",
	].join("\n")

	function compile(gl, type, src) {
		var s = gl.createShader(type)
		gl.shaderSource(s, src)
		gl.compileShader(s)
		if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
			throw new Error(gl.getShaderInfoLog(s) || "shader")
		}
		return s
	}
	function program(gl, vs, fs) {
		var p = gl.createProgram()
		gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs))
		gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs))
		gl.linkProgram(p)
		if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || "link")
		return p
	}
	function buffer(gl, data) {
		var b = gl.createBuffer()
		gl.bindBuffer(gl.ARRAY_BUFFER, b)
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW)
		return b
	}

	/* ---------------------------------------------------------------- сцена */
	function boot(canvas) {
		var wrap = canvas.parentNode
		var gl = null
		try {
			gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: false }) ||
				canvas.getContext("experimental-webgl")
		} catch (e) {
			gl = null
		}
		if (!gl) {
			wrap.classList.add("no-gl")
			return
		}

		var pSolid, pLine
		try {
			pSolid = program(gl, VS_SOLID, FS_SOLID)
			pLine = program(gl, VS_LINE, FS_LINE)
		} catch (e) {
			wrap.classList.add("no-gl")
			return
		}

		var sphere = sphereMesh(1)
		var shell = sphereMesh(0)
		var torus = torusMesh(1, 0.34, 46, 18)
		var meshes = {
			sphere: { pos: buffer(gl, sphere.pos), nor: buffer(gl, sphere.nor), count: sphere.pos.length / 3 },
			shellLines: { pos: buffer(gl, shell.edges), count: shell.edges.length / 3 },
			sphereLines: { pos: buffer(gl, sphere.edges), count: sphere.edges.length / 3 },
			torus: { pos: buffer(gl, torus.pos), nor: buffer(gl, torus.nor), count: torus.pos.length / 3 },
		}

		var objects = [
			{ mesh: "torus", color: [0.29, 0.42, 0.95], color2: [0.55, 0.48, 1.0], pos: [-1.55, 0.72, -1.1], scale: 0.86, spin: [0.17, 0.26, 0.05], alpha: 0.96 },
			{ mesh: "sphere", color: [0.95, 0.19, 0.31], color2: [1.0, 0.5, 0.36], pos: [1.68, -0.86, -0.7], scale: 0.52, spin: [0.23, -0.19, 0.1], alpha: 0.96 },
			{ mesh: "torus", color: [0.1, 0.78, 0.62], color2: [0.42, 0.95, 0.84], pos: [1.5, 1.22, -1.9], scale: 0.42, spin: [-0.3, 0.2, 0.22], alpha: 0.94 },
			{ mesh: "sphere", color: [0.42, 0.34, 0.9], color2: [0.6, 0.55, 1.0], pos: [-1.9, -1.15, -1.7], scale: 0.34, spin: [0.14, 0.3, -0.12], alpha: 0.92 },
		]

		var aSolidPos = gl.getAttribLocation(pSolid, "aPos")
		var aSolidNor = gl.getAttribLocation(pSolid, "aNor")
		var uSolid = {
			proj: gl.getUniformLocation(pSolid, "uProj"),
			model: gl.getUniformLocation(pSolid, "uModel"),
			normal: gl.getUniformLocation(pSolid, "uNormal"),
			color: gl.getUniformLocation(pSolid, "uColor"),
			color2: gl.getUniformLocation(pSolid, "uColor2"),
			alpha: gl.getUniformLocation(pSolid, "uAlpha"),
		}
		var aLinePos = gl.getAttribLocation(pLine, "aPos")
		var uLine = {
			proj: gl.getUniformLocation(pLine, "uProj"),
			model: gl.getUniformLocation(pLine, "uModel"),
			color: gl.getUniformLocation(pLine, "uColor"),
			alpha: gl.getUniformLocation(pLine, "uAlpha"),
		}

		var proj = mIdent()
		function resize() {
			var dpr = Math.min(window.devicePixelRatio || 1, 2)
			var w = wrap.clientWidth || 600
			var h = wrap.clientHeight || 440
			canvas.width = Math.floor(w * dpr)
			canvas.height = Math.floor(h * dpr)
			canvas.style.width = w + "px"
			canvas.style.height = h + "px"
			gl.viewport(0, 0, canvas.width, canvas.height)
			proj = mPerspective(0.92, w / Math.max(h, 1), 0.1, 100)
		}
		resize()
		window.addEventListener("resize", resize)

		var mx = 0,
			my = 0,
			tx = 0,
			ty = 0
		window.addEventListener(
			"pointermove",
			function (e) {
				var r = wrap.getBoundingClientRect()
				tx = ((e.clientX - r.left) / Math.max(r.width, 1) - 0.5) * 0.5
				ty = ((e.clientY - r.top) / Math.max(r.height, 1) - 0.5) * 0.4
			},
			{ passive: true }
		)

		var visible = true
		if (window.IntersectionObserver) {
			new IntersectionObserver(function (es) {
				visible = es[0].isIntersecting
			}).observe(wrap)
		}

		var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
		gl.enable(gl.DEPTH_TEST)
		gl.clearColor(0, 0, 0, 0)

		function drawSolid(mesh, model, color, color2, alpha) {
			gl.useProgram(pSolid)
			gl.uniformMatrix4fv(uSolid.proj, false, proj)
			gl.uniformMatrix4fv(uSolid.model, false, model)
			gl.uniformMatrix3fv(uSolid.normal, false, mNormal3(model))
			gl.uniform3fv(uSolid.color, color)
			gl.uniform3fv(uSolid.color2, color2)
			gl.uniform1f(uSolid.alpha, alpha)
			gl.bindBuffer(gl.ARRAY_BUFFER, mesh.pos)
			gl.enableVertexAttribArray(aSolidPos)
			gl.vertexAttribPointer(aSolidPos, 3, gl.FLOAT, false, 0, 0)
			gl.bindBuffer(gl.ARRAY_BUFFER, mesh.nor)
			gl.enableVertexAttribArray(aSolidNor)
			gl.vertexAttribPointer(aSolidNor, 3, gl.FLOAT, false, 0, 0)
			gl.drawArrays(gl.TRIANGLES, 0, mesh.count)
		}
		function drawLines(mesh, model, color, alpha) {
			gl.useProgram(pLine)
			gl.uniformMatrix4fv(uLine.proj, false, proj)
			gl.uniformMatrix4fv(uLine.model, false, model)
			gl.uniform3fv(uLine.color, color)
			gl.uniform1f(uLine.alpha, alpha)
			gl.bindBuffer(gl.ARRAY_BUFFER, mesh.pos)
			gl.enableVertexAttribArray(aLinePos)
			gl.vertexAttribPointer(aLinePos, 3, gl.FLOAT, false, 0, 0)
			gl.drawArrays(gl.LINES, 0, mesh.count)
		}

		var t0 = performance.now()
		function frame(now) {
			var t = reduced ? 0 : (now - t0) / 1000
			if (visible) {
				mx += (tx - mx) * 0.06
				my += (ty - my) * 0.06
				gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
				var view = mMul(mTranslate(mx * 1.2, -my * 1.2, -6.1), mMul(mRotX(my * 0.45), mRotY(mx * 0.9)))
				var base = mMul(proj, view)
				var savedProj = proj
				proj = base

				/* центральный каркасный икосаэдр + светящееся ядро */
				var spin = mMul(mRotY(t * 0.16), mMul(mRotX(t * 0.1), mRotZ(t * 0.05)))
				var core = mMul(spin, mScale(1.72))
				gl.enable(gl.BLEND)
				gl.blendFunc(gl.SRC_ALPHA, gl.ONE)
				gl.depthMask(false)
				drawSolid(meshes.sphere, mMul(spin, mScale(0.82 + Math.sin(t * 0.8) * 0.03)), [0.04, 0.42, 0.38], [0.18, 0.95, 0.75], 0.5)
				drawLines(meshes.shellLines, core, [0.18, 0.88, 0.68], 0.88)
				drawLines(meshes.sphereLines, mMul(mMul(mRotY(-t * 0.1), mRotZ(t * 0.07)), mScale(2.42)), [0.3, 0.55, 0.95], 0.2)
				gl.depthMask(true)
				gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

				/* плавающие тела */
				for (var i = 0; i < objects.length; i++) {
					var o = objects[i]
					var bob = Math.sin(t * 0.7 + i * 1.7) * 0.16
					var model = mMul(
						mTranslate(o.pos[0], o.pos[1] + bob, o.pos[2]),
						mMul(mMul(mRotY(t * o.spin[1]), mMul(mRotX(t * o.spin[0]), mRotZ(t * o.spin[2]))), mScale(o.scale))
					)
					drawSolid(meshes[o.mesh], model, o.color, o.color2, o.alpha)
				}
				gl.disable(gl.BLEND)
				proj = savedProj
			}
			requestAnimationFrame(frame)
		}
		requestAnimationFrame(frame)
	}

	function init() {
		var nodes = document.querySelectorAll("canvas.gl-canvas")
		for (var i = 0; i < nodes.length; i++) {
			try {
				boot(nodes[i])
			} catch (e) {
				nodes[i].parentNode.classList.add("no-gl")
			}
		}
	}
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init)
	else init()
})()
