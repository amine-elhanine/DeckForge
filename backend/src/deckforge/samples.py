"""A sample deck exercising every element type.

Used by the CLI (`deckforge render-sample`), by the test-suite as a golden
fixture, and as a reference for what the deck JSON looks like in practice.
"""

from __future__ import annotations

from deckforge.models.deck import (
    BulletsElement,
    Card,
    CardsElement,
    ChartElement,
    ChartSeries,
    ChartSpec,
    CodeElement,
    DeckMetadata,
    DiagramElement,
    ImageElement,
    MetricElement,
    Presentation,
    QuoteElement,
    Reference,
    Section,
    Slide,
    TableElement,
    TextElement,
    TimelineElement,
    TimelineEntry,
)
from deckforge.models.enums import ChartKind, SlideKind, TextRole


def sample_deck(theme: str = "modern_dark") -> Presentation:
    """Build a twelve-slide demo deck about reinforcement learning."""
    intro = Section(title="Foundations", order=0)
    practice = Section(title="In practice", order=1)
    closing = Section(title="Wrap up", order=2)

    deck = Presentation(
        title="Reinforcement Learning",
        subtitle="From bandits to RLHF",
        description="A 20-minute primer for engineers shipping their first RL system.",
        theme=theme,
        sections=[intro, practice, closing],
        meta=DeckMetadata(
            audience="software engineers new to RL",
            tone="clear, concrete, lightly technical",
            goal="leave with a working mental model and one thing to try",
            duration_minutes=20,
            language="en",
            keywords=["reinforcement learning", "policy", "reward", "RLHF"],
        ),
        references=[
            Reference(
                title="Reinforcement Learning: An Introduction",
                authors=["Sutton, R.", "Barto, A."],
                year=2018,
                publisher="MIT Press",
            ),
        ],
    )

    deck.slides = [
        Slide(
            kind=SlideKind.COVER,
            section_id=intro.id,
            eyebrow="Engineering primer",
            title="Reinforcement Learning",
            subtitle="From bandits to RLHF — what actually matters when you ship one",
            notes="Set expectations: 20 minutes, no maths beyond expectations, one runnable idea.",
        ),
        Slide(
            kind=SlideKind.AGENDA,
            section_id=intro.id,
            title="What we'll cover",
            elements=[
                BulletsElement(
                    items=[
                        "The loop: state, action, reward",
                        "Why credit assignment is the hard part",
                        "Where RL beats supervised learning — and where it doesn't",
                        "RLHF in one slide",
                        "A checklist before you start",
                    ]
                )
            ],
            notes="Signpost the arc so people know when to save questions.",
        ),
        Slide(
            kind=SlideKind.SECTION,
            section_id=intro.id,
            eyebrow="Part one",
            title="The loop",
            subtitle="Everything else is a variation on four boxes",
            metadata={"section_number": 1},
        ),
        Slide(
            kind=SlideKind.CONTENT,
            section_id=intro.id,
            title="The core loop",
            subtitle="An agent learns by acting, not by being told",
            elements=[
                BulletsElement(
                    items=[
                        "The **agent** observes a state",
                        "It selects an **action** from a policy",
                        "The environment returns a **reward** and the next state",
                        "The policy updates so good actions become more likely",
                    ]
                ),
                DiagramElement(
                    source=(
                        "flowchart LR\n"
                        "  A[Agent] -- action --> E[Environment]\n"
                        "  E -- state, reward --> A"
                    ),
                    caption="The agent-environment loop",
                ),
            ],
            notes="Stress that the reward is the only supervision. Everything downstream inherits its flaws.",
        ),
        Slide(
            kind=SlideKind.QUOTE,
            section_id=intro.id,
            title="",
            elements=[
                QuoteElement(
                    text="The reward hypothesis: all of what we mean by goals can be "
                    "described as the maximisation of expected cumulative reward.",
                    attribution="Sutton & Barto",
                    role="Reinforcement Learning: An Introduction",
                )
            ],
            notes="Land the point, then immediately complicate it on the next slide.",
        ),
        Slide(
            kind=SlideKind.COMPARISON,
            section_id=practice.id,
            title="Supervised learning vs. RL",
            elements=[
                TextElement(text="**Supervised**", role=TextRole.LEAD),
                BulletsElement(
                    items=["Labels are given", "IID samples", "Failure looks like error"]
                ),
                TextElement(text="**Reinforcement**", role=TextRole.LEAD),
                BulletsElement(
                    items=[
                        "Labels are earned",
                        "Your policy shapes the data",
                        "Failure looks like collapse",
                    ]
                ),
            ],
            notes="The second column is why RL projects fail for reasons that look like infrastructure bugs.",
        ),
        Slide(
            kind=SlideKind.CHART,
            section_id=practice.id,
            title="Sample efficiency, roughly",
            elements=[
                ChartElement(
                    title="Environment steps to reach a target score (millions)",
                    chart=ChartSpec(
                        kind=ChartKind.COLUMN,
                        categories=["DQN", "PPO", "SAC", "Model-based"],
                        series=[ChartSeries(name="steps (M)", values=[10.0, 6.2, 3.8, 0.9])],
                        y_label="steps (millions)",
                        legend=False,
                    ),
                ),
                TextElement(
                    text="Model-based methods buy sample efficiency with compute and complexity.",
                    role=TextRole.CAPTION,
                ),
            ],
            notes="Numbers are illustrative, not a benchmark. Say so out loud.",
        ),
        Slide(
            kind=SlideKind.METRICS,
            section_id=practice.id,
            title="What teams actually measure",
            elements=[
                MetricElement(
                    value="72%",
                    label="runs that reproduce",
                    delta="+18pts",
                    trend="up",
                    icon="refresh",
                ),
                MetricElement(value="4.1×", label="compute vs. supervised baseline", icon="cpu"),
                MetricElement(
                    value="11",
                    label="median reward iterations",
                    delta="-3",
                    trend="down",
                    icon="target",
                ),
            ],
            notes="Reproducibility is the metric nobody puts in the paper and everybody argues about.",
        ),
        Slide(
            kind=SlideKind.TIMELINE,
            section_id=practice.id,
            title="How a project usually goes",
            elements=[
                TimelineElement(
                    entries=[
                        TimelineEntry(
                            label="Week 1",
                            title="Environment",
                            body="Wrap the simulator; make it deterministic.",
                            status="done",
                        ),
                        TimelineEntry(
                            label="Week 2–3",
                            title="Reward",
                            body="Write it, watch it get gamed, rewrite it.",
                            status="done",
                        ),
                        TimelineEntry(
                            label="Week 4–6",
                            title="Baselines",
                            body="PPO first. Resist novelty.",
                            status="active",
                        ),
                        TimelineEntry(
                            label="Week 7+",
                            title="Scale",
                            body="Only after a reproducible baseline.",
                            status="planned",
                        ),
                    ]
                )
            ],
            notes="Most of the value is in weeks 1–3 and most of the excitement is in week 7. Plan accordingly.",
        ),
        Slide(
            kind=SlideKind.CONTENT,
            section_id=practice.id,
            title="RLHF in one slide",
            elements=[
                CardsElement(
                    columns=3,
                    cards=[
                        Card(
                            title="Collect preferences",
                            body="Humans rank pairs of model outputs.",
                            icon="users",
                            badge="1",
                        ),
                        Card(
                            title="Fit a reward model",
                            body="Train a scorer to agree with those rankings.",
                            icon="brain",
                            badge="2",
                        ),
                        Card(
                            title="Optimise the policy",
                            body="PPO against the reward model, with a KL leash.",
                            icon="target",
                            badge="3",
                        ),
                    ],
                )
            ],
            notes="The KL penalty is the whole safety story in this diagram. Do not skip it.",
        ),
        Slide(
            kind=SlideKind.TABLE,
            section_id=practice.id,
            title="Choosing an algorithm",
            elements=[
                TableElement(
                    columns=["Setting", "Start with", "Why"],
                    rows=[
                        [
                            "Discrete actions, cheap sim",
                            "PPO",
                            "Stable, forgiving of bad hyperparameters",
                        ],
                        ["Continuous control", "SAC", "Sample efficient off-policy learning"],
                        [
                            "Expensive real-world steps",
                            "Model-based",
                            "Learn the dynamics, then plan",
                        ],
                        ["Language models", "PPO / DPO", "Reward model plus a KL constraint"],
                    ],
                )
            ],
        ),
        Slide(
            kind=SlideKind.CONTENT,
            section_id=closing.id,
            title="One thing to try this week",
            elements=[
                CodeElement(
                    language="python",
                    source=(
                        "import gymnasium as gym\n\n"
                        "env = gym.make('CartPole-v1')\n"
                        "state, _ = env.reset(seed=0)\n"
                        "for _ in range(500):\n"
                        "    action = policy(state)\n"
                        "    state, reward, done, truncated, _ = env.step(action)\n"
                        "    if done or truncated:\n"
                        "        state, _ = env.reset()"
                    ),
                ),
                TextElement(
                    text="Instrument the reward before you tune anything else.",
                    role=TextRole.LEAD,
                ),
            ],
            notes="Give them a concrete first commit. Momentum beats theory.",
        ),
        Slide(
            kind=SlideKind.IMAGE,
            section_id=closing.id,
            title="Further reading",
            elements=[
                ImageElement(
                    src="",
                    alt="Placeholder for a diagram of the RLHF pipeline",
                    caption="Swap in your own diagram export",
                ),
                BulletsElement(
                    items=["Sutton & Barto (2018)", "Spinning Up in Deep RL", "The PPO paper"]
                ),
            ],
        ),
        Slide(
            kind=SlideKind.ENDING,
            section_id=closing.id,
            eyebrow="Thanks",
            title="Questions?",
            subtitle="Start with the reward. Everything else is downstream.",
            notes="Leave the loop diagram on screen if there is time for questions.",
        ),
    ]
    return deck
