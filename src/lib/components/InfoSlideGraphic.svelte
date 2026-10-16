<script lang="ts">
	type GraphicKind = 'select' | 'colours' | 'ranking' | 'hover' | 'inspect' | 'states';

	interface Props {
		kind: GraphicKind;
		label: string;
	}

	let { kind, label }: Props = $props();

	const hexes = [
		[72, 67],
		[126, 67],
		[180, 67],
		[99, 114],
		[153, 114],
		[207, 114],
		[72, 161],
		[126, 161],
		[180, 161],
		[234, 161]
	];
	const affinityColours = [
		'#fee08b',
		'#d9ef8b',
		'#91cf60',
		'#fc8d59',
		'#1a9850',
		'#d9ef8b',
		'#d73027',
		'#fee08b',
		'#91cf60',
		'#fc8d59'
	];

	function points(x: number, y: number, radius = 30) {
		const half = radius / 2;
		return `${x},${y - radius} ${x + radius * 0.87},${y - half} ${x + radius * 0.87},${y + half} ${x},${y + radius} ${x - radius * 0.87},${y + half} ${x - radius * 0.87},${y - half}`;
	}
</script>

<svg class="graphic" viewBox="0 0 560 280" role="img" aria-label={label}>
	<rect x="1" y="1" width="558" height="278" rx="14" fill="#ebe7dc" stroke="#171717" />

	{#if kind === 'states'}
		<rect x="28" y="29" width="240" height="222" rx="9" fill="#f5f1e8" stroke="#171717" />
		<text x="46" y="57" class="eyebrow">STOPS, BUT NO DIRECT ROUTE</text>
		<polygon points={points(105, 111, 34)} fill="#fc8d59" stroke="#fff" stroke-width="3" />
		<polygon points={points(181, 111, 34)} fill="#d73027" stroke="#fff" stroke-width="3" />
		<circle cx="105" cy="111" r="7" fill="#171717" stroke="#fff" stroke-width="3" />
		<circle cx="181" cy="111" r="7" fill="#171717" stroke="#fff" stroke-width="3" />
		<path d="M119 111 H167" stroke="#171717" stroke-width="3" stroke-dasharray="5 5" />
		<path d="M137 100 L149 122 M149 100 L137 122" stroke="#d73027" stroke-width="4" />
		<rect x="46" y="177" width="204" height="44" rx="5" fill="#fff" />
		<rect x="46" y="177" width="5" height="44" rx="2" fill="#2563eb" />
		<text x="61" y="204" class="panel-title">No direct routes available</text>

		<rect x="292" y="29" width="240" height="222" rx="9" fill="#f5f1e8" stroke="#171717" />
		<text x="310" y="57" class="eyebrow">NO STOPS IN THE AREA</text>
		<polygon points={points(369, 111, 34)} fill="#d73027" stroke="#fff" stroke-width="3" />
		<polygon points={points(445, 111, 34)} fill="#d73027" stroke="#fff" stroke-width="3" />
		<circle cx="407" cy="111" r="20" fill="#fff" />
		<path d="M396 100 L418 122 M418 100 L396 122" stroke="#d73027" stroke-width="5" />
		<rect x="310" y="177" width="204" height="44" rx="5" fill="#fff" />
		<rect x="310" y="177" width="5" height="44" rx="2" fill="#2563eb" />
		<text x="325" y="204" class="panel-title">No transit stops</text>
	{:else}
		<path
			d="M-24 227 C55 176 125 238 196 189 S289 142 354 184 S468 226 584 171"
			fill="none"
			stroke="#8ecae6"
			stroke-width="25"
		/>
		<path d="M24 43 L303 219" stroke="#d0cabd" stroke-width="5" />
		<path d="M30 205 L291 47" stroke="#d0cabd" stroke-width="4" />

		<g stroke="#fff" stroke-width="3">
			{#each hexes as [x, y], index (index)}
				<polygon points={points(x, y)} fill={affinityColours[index]} />
			{/each}
		</g>

		{#if kind === 'select'}
			<polygon points={points(153, 114)} fill="none" stroke="#2563eb" stroke-width="6" />
			<circle cx="153" cy="114" r="7" fill="#2563eb" stroke="#fff" stroke-width="3" />
			<path d="M169 136 L187 184 L198 168 L216 186" class="cursor" />
			<rect x="341" y="43" width="185" height="183" rx="8" fill="#f5f1e8" stroke="#171717" />
			<text x="359" y="72" class="eyebrow">STARTING AREA</text>
			<text x="359" y="103" class="panel-title">Adelaide Street</text>
			<text x="359" y="122" class="panel-copy">Stop 28</text>
			<line x1="359" y1="145" x2="508" y2="145" stroke="#c6c0b4" />
			<circle cx="370" cy="177" r="6" fill="#2563eb" />
			<text x="385" y="181" class="small-copy">Selected source</text>
		{:else if kind === 'colours'}
			<rect x="42" y="218" width="476" height="38" rx="19" fill="#fff" fill-opacity="0.85" />
			<text x="60" y="242" class="small-copy">LOWER</text>
			<circle cx="125" cy="237" r="9" fill="#d73027" />
			<circle cx="155" cy="237" r="9" fill="#fc8d59" />
			<circle cx="185" cy="237" r="9" fill="#fee08b" />
			<circle cx="215" cy="237" r="9" fill="#d9ef8b" />
			<circle cx="245" cy="237" r="9" fill="#91cf60" />
			<circle cx="275" cy="237" r="9" fill="#1a9850" />
			<text x="299" y="242" class="small-copy">HIGHER</text>
			<circle cx="389" cy="237" r="6" fill="#2563eb" />
			<text x="403" y="242" class="small-copy">Smoothed model</text>
		{:else if kind === 'ranking'}
			<rect x="304" y="27" width="228" height="226" rx="8" fill="#f5f1e8" stroke="#171717" />
			<text x="320" y="55" class="eyebrow">MOST ACCESSIBLE AREAS</text>
			<g>
				<rect x="320" y="70" width="196" height="45" rx="5" fill="#fff" />
				<text x="331" y="89" class="panel-title">Cultural Centre</text>
				<text x="331" y="105" class="small-copy">~0.5 min</text>
				<rect x="320" y="121" width="196" height="45" rx="5" fill="#fff" />
				<text x="331" y="140" class="panel-title">Roma Street</text>
				<text x="331" y="156" class="small-copy">~0.5 min</text>
				<rect x="320" y="172" width="196" height="45" rx="5" fill="#fff" />
				<text x="331" y="191" class="panel-title">South Bank</text>
				<text x="331" y="207" class="small-copy">~0.5 min</text>
			</g>
		{:else if kind === 'hover'}
			<polygon points={points(153, 114)} fill="none" stroke="#2563eb" stroke-width="6" />
			<path d="M169 136 L187 184 L198 168 L216 186" class="cursor" />
			<path d="M246 115 H294" stroke="#2563eb" stroke-width="3" stroke-dasharray="5 5" />
			<path d="M286 108 L297 115 L286 122" fill="none" stroke="#2563eb" stroke-width="3" />
			<rect x="304" y="27" width="228" height="226" rx="8" fill="#f5f1e8" stroke="#171717" />
			<text x="320" y="55" class="eyebrow">MOST ACCESSIBLE AREAS</text>
			<rect x="320" y="70" width="196" height="45" rx="5" fill="#fff" />
			<text x="331" y="89" class="panel-title">Cultural Centre</text>
			<text x="331" y="105" class="small-copy">~0.5 min</text>
			<rect x="320" y="121" width="196" height="53" rx="5" fill="#dbeafe" />
			<rect x="320" y="121" width="5" height="53" rx="2" fill="#2563eb" />
			<text x="334" y="143" class="panel-title">RBWH station</text>
			<text x="334" y="161" class="small-copy">~0.5 min</text>
			<rect x="320" y="180" width="196" height="45" rx="5" fill="#fff" />
			<text x="331" y="199" class="panel-title">South Bank</text>
			<text x="331" y="215" class="small-copy">~0.5 min</text>
		{:else}
			<polygon points={points(153, 114)} fill="none" stroke="#2563eb" stroke-width="6" />
			<rect x="43" y="215" width="62" height="31" rx="5" fill="#fff" stroke="#171717" />
			<text x="58" y="236" class="key-label">SHIFT</text>
			<text x="115" y="236" class="plus-label">+</text>
			<path d="M152 203 L170 251 L181 234 L198 252" class="cursor" />
			<rect x="287" y="27" width="245" height="226" rx="8" fill="#e5e5e5" stroke="#171717" />
			<text x="303" y="55" class="eyebrow">DIRECT ROUTES</text>
			{#each [['66', 'CityGlider', '~12 min'], ['60', 'Blue CityGlider', '~15 min'], ['⛴', 'CityCat', '~30 min']] as route, index (route[0])}
				<rect x="303" y={70 + index * 56} width="213" height="48" rx="5" fill="#fff" />
				<circle
					cx="322"
					cy={94 + index * 56}
					r="11"
					fill={index === 0 ? '#2563eb' : index === 1 ? '#d97706' : '#0f766e'}
				/>
				<text x="322" y={98 + index * 56} class="route-number">{route[0]}</text>
				<text x="342" y={91 + index * 56} class="panel-title">{route[1]}</text>
				<text x="342" y={107 + index * 56} class="small-copy">{route[2]}</text>
			{/each}
		{/if}
	{/if}
</svg>

<style>
	.graphic {
		display: block;
		width: 100%;
		height: auto;
	}

	.graphic :global(text) {
		fill: #171717;
		font-family: ui-sans-serif, system-ui, sans-serif;
	}

	.eyebrow {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
	}

	.panel-title {
		font-size: 12px;
		font-weight: 650;
	}

	.panel-copy {
		font-size: 12px;
	}

	.small-copy {
		font-size: 11px;
	}

	.key-label {
		font-size: 11px;
		font-weight: 750;
		letter-spacing: 0.08em;
	}

	.plus-label {
		font-size: 18px;
		font-weight: 600;
	}

	.route-number {
		fill: #fff !important;
		font-size: 9px;
		font-weight: 750;
		text-anchor: middle;
	}

	.cursor {
		fill: #fff;
		stroke: #171717;
		stroke-width: 4;
	}
</style>
