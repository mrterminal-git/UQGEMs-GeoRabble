<script lang="ts">
	import { onMount } from 'svelte';
	import InfoSlideGraphic from './InfoSlideGraphic.svelte';

	interface Props {
		onClose: () => void;
	}

	type GraphicKind = 'select' | 'colours' | 'ranking' | 'hover' | 'inspect' | 'states';

	interface Slide {
		kind: GraphicKind;
		step: string;
		title: string;
		description: string;
		note: string;
		graphicLabel: string;
	}

	let { onClose }: Props = $props();

	const slides: Slide[] = [
		{
			kind: 'select',
			step: 'Start here',
			title: 'Choose a starting area',
			description:
				'Click any hexagon to make it your starting area. The map recolours to show how strongly it connects with the rest of Brisbane.',
			note: 'A normal click replaces the current starting area.',
			graphicLabel:
				'A simplified Brisbane map with one hexagon selected and its starting-area panel visible.'
		},
		{
			kind: 'colours',
			step: 'Map colours',
			title: 'Read the affinity pattern',
			description:
				'Greener areas have higher modelled transit affinity to your starting area; redder areas have lower affinity. The colour pattern uses spatial smoothing.',
			note: 'Colour alone does not guarantee a direct service—use the list to confirm one.',
			graphicLabel:
				'A row of map hexagons progressing from red for lower affinity to green for higher affinity.'
		},
		{
			kind: 'ranking',
			step: 'Ranked results',
			title: 'Scan the most accessible areas',
			description:
				'The list ranks destinations with scheduled routes that directly visit both the starting area and destination.',
			note: '“~12 min” is an estimated average service interval, not the journey time.',
			graphicLabel:
				'A simplified map beside a ranked list of accessible areas and their estimated intervals.'
		},
		{
			kind: 'hover',
			step: 'Map and list',
			title: 'Hover to match an area',
			description:
				'Hover over a hexagon to highlight its matching list entry. Hover over a list entry and the corresponding hexagon highlights on the map.',
			note: 'Results beyond the first 100 are automatically revealed when you hover over their hexagon.',
			graphicLabel:
				'A hovered map hexagon connected visually to its highlighted accessible-area list entry.'
		},
		{
			kind: 'inspect',
			step: 'Direct services',
			title: 'Shift-click a destination',
			description:
				'Hold Shift and click a destination hexagon to keep your starting area selected and open the direct route numbers and frequencies.',
			note: 'Selecting that destination in the list opens the same route panel.',
			graphicLabel:
				'A Shift key and cursor selecting a map hexagon beside a panel of direct routes and estimated intervals.'
		},
		{
			kind: 'states',
			step: 'Unavailable service',
			title: 'Understand the two empty states',
			description:
				'“No direct routes available” means the area has stops but no direct route from your source. “No transit stops” means no stops are mapped inside it.',
			note: 'Each status has one shared list entry, keeping the results compact.',
			graphicLabel:
				'Two simplified map examples comparing an area with stops but no direct route and an area with no transit stops.'
		}
	];

	let activeIndex = $state(0);
	let viewport: HTMLDivElement;
	let dialog: HTMLDivElement;
	let closeButton: HTMLButtonElement;

	function goToSlide(index: number, behavior: ScrollBehavior = 'smooth') {
		const nextIndex = Math.max(0, Math.min(slides.length - 1, index));
		activeIndex = nextIndex;
		viewport?.scrollTo({ left: viewport.clientWidth * nextIndex, behavior });
	}

	function handleScroll() {
		if (!viewport?.clientWidth) return;
		const nextIndex = Math.round(viewport.scrollLeft / viewport.clientWidth);
		if (nextIndex >= 0 && nextIndex < slides.length) activeIndex = nextIndex;
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			onClose();
			return;
		}

		if (event.key === 'ArrowLeft') {
			event.preventDefault();
			goToSlide(activeIndex - 1);
			return;
		}

		if (event.key === 'ArrowRight') {
			event.preventDefault();
			goToSlide(activeIndex + 1);
			return;
		}

		if (event.key !== 'Tab' || !dialog) return;

		const focusable = Array.from(
			dialog.querySelectorAll<HTMLElement>(
				'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
			)
		);
		if (focusable.length === 0) return;

		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		if (event.shiftKey && document.activeElement === first) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && document.activeElement === last) {
			event.preventDefault();
			first.focus();
		}
	}

	function handleResize() {
		goToSlide(activeIndex, 'auto');
	}

	onMount(() => closeButton?.focus());
</script>

<svelte:window onkeydown={handleKeydown} onresize={handleResize} />

<div
	class="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-3 sm:p-5"
	role="presentation"
	onclick={(event) => event.target === event.currentTarget && onClose()}
>
	<div
		bind:this={dialog}
		class="relative max-h-[94dvh] w-full max-w-2xl overflow-y-auto rounded-xl border border-black/20 bg-[#f5f1e8] shadow-2xl outline-none"
		role="dialog"
		aria-modal="true"
		aria-labelledby="info-title"
		aria-describedby="carousel-status"
		tabindex="-1"
	>
		<header
			class="sticky top-0 z-10 border-b border-black/15 bg-[#f5f1e8]/95 px-5 pb-3 pt-4 backdrop-blur-sm sm:px-6"
		>
			<div class="pr-8">
				<p class="mono-label mb-1 text-[10px] font-bold text-black/55">BRISBANE TRANSIT AFFINITY</p>
				<h2 id="info-title" class="mono-label text-sm font-bold text-black">HOW TO USE THE MAP</h2>
			</div>

			<button
				bind:this={closeButton}
				type="button"
				onclick={onClose}
				title="Close"
				aria-label="Close map guide"
				class="absolute right-3 top-3 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full text-black transition-colors hover:bg-black/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<line x1="18" y1="6" x2="6" y2="18" />
					<line x1="6" y1="6" x2="18" y2="18" />
				</svg>
			</button>

			<div class="mt-3 grid grid-cols-6 gap-1.5" aria-label="Guide progress">
				{#each slides as slide, index (slide.kind)}
					<button
						type="button"
						onclick={() => goToSlide(index)}
						class="group h-3 cursor-pointer rounded-full py-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
						aria-label={`Go to slide ${index + 1}: ${slide.title}`}
						aria-current={activeIndex === index ? 'step' : undefined}
					>
						<span
							class="block h-1 rounded-full transition-colors {index <= activeIndex
								? 'bg-blue-700'
								: 'bg-black/20 group-hover:bg-black/35'}"
						></span>
					</button>
				{/each}
			</div>
		</header>

		<div
			bind:this={viewport}
			class="carousel-viewport flex overflow-x-auto"
			role="region"
			aria-roledescription="carousel"
			aria-label="Map guide"
			onscroll={handleScroll}
		>
			{#each slides as slide, index (slide.kind)}
				<article
					class="w-full shrink-0 px-5 pb-4 pt-5 sm:px-6"
					role="group"
					aria-roledescription="slide"
					aria-label={`${index + 1} of ${slides.length}: ${slide.title}`}
					aria-hidden={activeIndex !== index}
				>
					<InfoSlideGraphic kind={slide.kind} label={slide.graphicLabel} />

					<div class="mx-auto mt-5 max-w-xl">
						<p class="mono-label mb-1.5 text-[10px] font-bold uppercase text-blue-800">
							{slide.step}
						</p>
						<h3 class="text-xl font-semibold leading-tight text-black sm:text-2xl">
							{slide.title}
						</h3>
						<p class="mt-2 text-sm leading-relaxed text-black/75 sm:text-[15px]">
							{slide.description}
						</p>
						<div
							class="mt-3 flex gap-2.5 rounded-md bg-white/75 p-3 text-xs leading-relaxed text-black/70 sm:text-sm"
						>
							<svg
								class="mt-0.5 shrink-0 text-blue-700"
								xmlns="http://www.w3.org/2000/svg"
								width="16"
								height="16"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								aria-hidden="true"
							>
								<circle cx="12" cy="12" r="9" />
								<path d="M12 11v5" />
								<path d="M12 8h.01" />
							</svg>
							<p>{slide.note}</p>
						</div>
					</div>
				</article>
			{/each}
		</div>

		<footer
			class="flex items-center justify-between gap-3 border-t border-black/15 px-5 py-3 sm:px-6"
		>
			<button
				type="button"
				onclick={() => goToSlide(activeIndex - 1)}
				disabled={activeIndex === 0}
				class="nav-button"
				aria-label="Previous guide slide"
			>
				<svg
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					aria-hidden="true"
				>
					<path d="m15 18-6-6 6-6" />
				</svg>
				<span>Previous</span>
			</button>

			<div class="text-center">
				<p
					id="carousel-status"
					class="mono-label text-[10px] font-bold text-black/55"
					aria-live="polite"
				>
					{activeIndex + 1} OF {slides.length}
				</p>
				<a
					href="https://github.com/mrterminal-git/UQGEMs-GeoRabble"
					target="_blank"
					rel="noopener noreferrer"
					class="mt-1 inline-block text-[11px] font-semibold text-black/65 underline decoration-black/25 underline-offset-2 hover:text-black"
				>
					Project details
				</a>
			</div>

			<button
				type="button"
				onclick={() => goToSlide(activeIndex + 1)}
				disabled={activeIndex === slides.length - 1}
				class="nav-button"
				aria-label="Next guide slide"
			>
				<span>Next</span>
				<svg
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					aria-hidden="true"
				>
					<path d="m9 18 6-6-6-6" />
				</svg>
			</button>
		</footer>
	</div>
</div>

<style>
	.mono-label {
		font-family:
			ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
			monospace;
		letter-spacing: 0.07em;
	}

	.carousel-viewport {
		scroll-behavior: smooth;
		scroll-snap-type: x mandatory;
		scrollbar-width: none;
		overscroll-behavior-x: contain;
	}

	.carousel-viewport::-webkit-scrollbar {
		display: none;
	}

	.carousel-viewport article {
		scroll-snap-align: start;
		scroll-snap-stop: always;
	}

	.nav-button {
		display: inline-flex;
		min-width: 5.75rem;
		align-items: center;
		justify-content: center;
		gap: 0.25rem;
		border: 1px solid rgb(0 0 0 / 0.25);
		border-radius: 0.375rem;
		padding: 0.45rem 0.65rem;
		font-size: 0.75rem;
		font-weight: 700;
		color: #171717;
		cursor: pointer;
		transition:
			background-color 150ms ease,
			opacity 150ms ease;
	}

	.nav-button:hover:not(:disabled) {
		background: rgb(0 0 0 / 0.06);
	}

	.nav-button:focus-visible {
		outline: 2px solid #1d4ed8;
		outline-offset: 2px;
	}

	.nav-button:disabled {
		cursor: default;
		opacity: 0.28;
	}

	@media (max-width: 420px) {
		.nav-button {
			min-width: 2.5rem;
			padding-inline: 0.5rem;
		}

		.nav-button span {
			display: none;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.carousel-viewport {
			scroll-behavior: auto;
		}
	}
</style>
