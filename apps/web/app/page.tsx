import Link from "next/link";
import {
  ArrowUpRight,
  ArrowRight,
  Monitor,
  ShieldCheck,
  Command,
  MousePointer2,
  Terminal,
  Globe,
  Folder,
} from "lucide-react";
import { Mark } from "@/components/brand";
export default function Home() {
  return (
    <main className="landing">
      <nav className="landing-nav">
        <Link href="/" className="brand">
          <Mark />
          cubicle<span className="tag">EARLY ACCESS</span>
        </Link>
        <div className="nav-links">
          <a href="#how">How it works</a>
          <a href="#pricing">Pricing</a>
          <Link href="/login">
            Sign in <ArrowUpRight size={14} />
          </Link>
        </div>
      </nav>
      <section className="hero">
        <div className="eyebrow">
          <span className="pulse-dot" /> YOUR AGENT. ITS OWN SPACE.
        </div>
        <h1>
          Ideas need room.
          <br />
          <span>Give yours a computer.</span>
        </h1>
        <p>
          A persistent desktop for your AI agent. Give it a task,
          <br className="desktop-only" /> watch it work, and step in whenever
          you need.
        </p>
        <div className="hero-actions">
          <Link className="button primary" href="/login">
            Create your workspace <ArrowRight size={16} />
          </Link>
          <Link className="button ghost" href="/trial">
            Explore the 7-day trial <ArrowUpRight size={15} />
          </Link>
        </div>
        <p className="hero-note">
          Your tools. Your API key. A desktop that stays yours.
        </p>
      </section>
      <section
        className="product-scene"
        aria-label="Illustration of the workspace layout"
      >
        <div className="scene-top">
          <div className="traffic">
            <i />
            <i />
            <i />
          </div>
          <span>
            Personal workspace <span className="muted">/</span> My computer
          </span>
          <span className="tag">WORKSPACE PREVIEW</span>
        </div>
        <div className="scene-body">
          <aside className="scene-rail">
            <Mark size={22} />
            <Monitor size={19} />
            <Folder size={19} />
            <Command size={19} />
          </aside>
          <div className="scene-desktop">
            <div className="landscape">
              <div className="landscape-orb" />
              <div className="mountain one" />
              <div className="mountain two" />
              <div className="mountain three" />
              <div className="wallpaper-word">Space to do more.</div>
              <div className="dock">
                <Globe />
                <Folder />
                <Terminal />
              </div>
            </div>
            <div className="scene-tabs">
              <span>Files</span>
              <span>Terminal</span>
              <span>Activity</span>
            </div>
            <div className="scene-file">
              <Folder size={16} /> Workspace{" "}
              <span>Ready for your next idea</span>
            </div>
          </div>
          <div className="scene-chat">
            <div>
              <span className="tiny-label">YOUR AGENT</span>
              <h3>
                A little less busywork.
                <br />A lot more possibility.
              </h3>
              <p>
                Research, create, organize.
                <br />
                All in one shared view.
              </p>
            </div>
            <div className="scene-prompt">
              What would you like to work on?
              <span>
                <span>+</span>
                <ArrowUpRight size={20} />
              </span>
            </div>
          </div>
        </div>
      </section>
      <section id="how" className="feature-section">
        <div className="section-heading">
          <span className="eyebrow">FROM THOUGHT TO DONE</span>
          <h2>
            A familiar desktop.
            <br />
            An entirely new way to work.
          </h2>
        </div>
        <div className="feature-grid">
          {[
            [
              Monitor,
              "01",
              "Make yourself at home",
              "Launch a Linux computer with a browser, terminal, and files that stay with you.",
            ],
            [
              Command,
              "02",
              "Bring your intelligence",
              "Connect your Anthropic API key. Describe the outcome, and let the agent work.",
            ],
            [
              MousePointer2,
              "03",
              "Stay in the loop",
              "Watch the live desktop, approve important actions, or take over with one click.",
            ],
          ].map(([Icon, n, title, desc]) => {
            const I = Icon as typeof Monitor;
            return (
              <article key={String(n)}>
                <div className="feature-top">
                  <I size={23} />
                  <span>{String(n)}</span>
                </div>
                <h3>{String(title)}</h3>
                <p>{String(desc)}</p>
              </article>
            );
          })}
        </div>
      </section>
      <section id="pricing" className="pricing-section">
        <div>
          <span className="eyebrow">ROOM TO GET STARTED</span>
          <h2>
            One workspace.
            <br />
            Plenty of possibilities.
          </h2>
          <p className="muted">
            Pay for your computer here.
            <br />
            Pay your AI provider directly.
          </p>
          <Link href="/trial" className="text-link">
            Hold platform tokens? Explore the trial <ArrowUpRight size={14} />
          </Link>
        </div>
        <article className="price-card">
          <span className="tiny-label">PREPAID</span>
          <h3>
            USDC<span> / pay as you go</span>
          </h3>
          <p>For independent builders and small teams.</p>
          <ul>
            <li>Shared platform usage credits</li>
            <li>1 running computer · 2 saved computers</li>
            <li>Up to 3 workspace members</li>
            <li>Persistent files and browser profile</li>
            <li>Live desktop and autonomous task chat</li>
          </ul>
          <Link className="button primary" href="/login">
            Get started <ArrowRight size={16} />
          </Link>
          <small>See current usage rates in your workspace.</small>
        </article>
      </section>
      <footer>
        <span className="brand">
          <Mark size={20} />
          cubicle
        </span>
        <span>A little space for your next big thing.</span>
        <Link href="/login">
          Open workspace <ArrowUpRight size={14} />
        </Link>
      </footer>
    </main>
  );
}
