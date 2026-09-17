#!/usr/bin/env node
/**
 * cubicle: command-line control of Cubicle computers.
 *   CUBICLE_API_URL (default http://localhost:8000) and CUBICLE_API_KEY, or --api / --key.
 * Node 22.18+ runs this TypeScript file directly.
 */
import { readFile, writeFile } from "node:fs/promises";
import { basename } from "node:path";
import { Cubicle, CubicleError } from "./src.ts";

const HELP = `usage: cubicle [--api URL] [--key KEY] <command> [args]

  workspaces                          list workspaces this key can see
  computers <workspace>               list computers
  get <computer>                      show one computer
  create <workspace> <name> [--cpu 1|2] [--memory 2|4] [--storage 20|50|100]
                                      [--resolution WxH] [--idle MIN] [--start]
  start <computer> [--wait]           start (and optionally wait until running)
  stop <computer>                     stop, saving the system
  rename <computer> <name>
  delete <computer> --confirm <name>  erase home and saved system
  screenshot <computer> [-o out.png]  save a PNG (default screenshot.png)
  click <computer> <x> <y> [--right|--middle|--double|--triple]
  drag <computer> <x1> <y1> <x2> <y2>
  scroll <computer> <x> <y> <up|down|left|right> [amount]
  type <computer> <text...>
  key <computer> <keys>               xdotool syntax: Return, ctrl+l, alt+F4
  bash <computer> <command...>
  files <computer> [path]
  upload <computer> <local> [remote]
  download <computer> <remote> [local]
  rm <computer> <remote>
  task <computer> <prompt...>         submit a built-in agent task (manage scope)
  events <computer>                   recent activity

  Most input commands accept --screen N (0 is the primary display).
  screens <computer>                  list displays
  screen-add <computer> [WxH]         add a display (up to four in total)
  screen-rm <computer> <N>            remove display N
  apps <computer>                     catalog with install state
  app-install <computer> <app>        install from the catalog (detached; poll apps)
  app-launch <computer> <app>         open an installed app on the desktop
  automations <computer>              list automations
  automation-add <computer> <json>    create from a JSON body (file path or inline)
  automation-run <automation>         run now
  automation-runs <automation>        execution history
  fleet <workspace> [--q text] [--status s] [--label l]
  label <computer> <label...>         replace a computer's labels
  bulk <workspace> <start|stop|add_label|remove_label> <ids,comma,separated> [--label l]
  move <computer> <workspace>         move a stopped computer to another workspace you own
  template-starters                   built-in template definitions
  templates <workspace>               your definitions and versions
  template-publish <workspace> <name> <spec.json>
  template-create <template> <name>   create a computer from a ready version
`;

function parse(argv: string[]) {
  const flags: Record<string, string | boolean> = {};
  const positional: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const name = a.slice(2);
      const next = argv[i + 1];
      if (
        next !== undefined &&
        !next.startsWith("--") &&
        !["right", "middle", "double", "triple", "wait", "start"].includes(name)
      ) {
        flags[name] = next;
        i++;
      } else flags[name] = true;
    } else if (a === "-o") {
      flags.out = argv[++i];
    } else positional.push(a);
  }
  return { flags, positional };
}

function print(value: unknown) {
  console.log(JSON.stringify(value, null, 2));
}

async function main() {
  const { flags, positional } = parse(process.argv.slice(2));
  const [command, ...args] = positional;
  if (!command || flags.help) {
    console.log(HELP);
    return;
  }
  const apiKey = (flags.key as string) || process.env.CUBICLE_API_KEY;
  if (!apiKey) throw new Error("Set CUBICLE_API_KEY or pass --key");
  const client = new Cubicle({
    baseUrl:
      (flags.api as string) ||
      process.env.CUBICLE_API_URL ||
      "http://localhost:8000",
    apiKey,
  });
  const need = (n: number) => {
    if (args.length < n)
      throw new Error(`${command} needs ${n} argument(s)\n\n${HELP}`);
  };
  switch (command) {
    case "workspaces":
      return print(await client.workspaces());
    case "computers":
      need(1);
      return print(await client.computers(args[0]));
    case "get":
      need(1);
      return print(await client.computer(args[0]));
    case "create": {
      need(2);
      const c = await client.create(args[0], {
        name: args[1],
        ...(flags.cpu ? { cpu: Number(flags.cpu) as 1 | 2 } : {}),
        ...(flags.memory ? { memory_gib: Number(flags.memory) as 2 | 4 } : {}),
        ...(flags.storage
          ? { storage_gib: Number(flags.storage) as 20 | 50 | 100 }
          : {}),
        ...(flags.resolution ? { resolution: flags.resolution as any } : {}),
        ...(flags.idle ? { idle_timeout_minutes: Number(flags.idle) } : {}),
      });
      if (flags.start) {
        await client.start(c.id);
        return print(await client.waitFor(c.id));
      }
      return print(c);
    }
    case "start": {
      need(1);
      const c = await client.start(args[0]);
      return print(flags.wait ? await client.waitFor(args[0]) : c);
    }
    case "stop":
      need(1);
      return print(await client.stop(args[0]));
    case "rename":
      need(2);
      return print(await client.rename(args[0], args.slice(1).join(" ")));
    case "delete":
      need(1);
      if (!flags.confirm)
        throw new Error("delete needs --confirm <exact computer name>");
      return print(await client.delete(args[0], String(flags.confirm)));
    case "screenshot": {
      need(1);
      const shot = await client.screenshot(args[0], Number(flags.screen || 0));
      const out = (flags.out as string) || "screenshot.png";
      await writeFile(out, Buffer.from(shot.image, "base64"));
      return console.log(`${out} (${shot.width}x${shot.height})`);
    }
    case "click": {
      need(3);
      const count = flags.double ? 2 : flags.triple ? 3 : 1;
      const button = flags.right ? "right" : flags.middle ? "middle" : "left";
      return print(
        await client.click(args[0], Number(args[1]), Number(args[2]), {
          button,
          count: count as 1 | 2 | 3,
          screen: Number(flags.screen || 0),
        }),
      );
    }
    case "drag":
      need(5);
      return print(
        await client.drag(
          args[0],
          [Number(args[1]), Number(args[2])],
          [Number(args[3]), Number(args[4])],
          Number(flags.screen || 0),
        ),
      );
    case "scroll":
      need(4);
      return print(
        await client.scroll(
          args[0],
          Number(args[1]),
          Number(args[2]),
          args[3] as any,
          args[4] ? Number(args[4]) : 3,
          Number(flags.screen || 0),
        ),
      );
    case "type":
      need(2);
      return print(
        await client.type(
          args[0],
          args.slice(1).join(" "),
          Number(flags.screen || 0),
        ),
      );
    case "key":
      need(2);
      return print(
        await client.key(args[0], args[1], Number(flags.screen || 0)),
      );
    case "bash": {
      need(2);
      const r = await client.bash(args[0], args.slice(1).join(" "));
      console.log(r.output);
      if (r.error) {
        console.error(r.error);
        process.exitCode = Number(r.exit_code) || 1;
      }
      return;
    }
    case "files":
      need(1);
      return print(await client.files(args[0], args[1] || ""));
    case "upload": {
      need(2);
      const bytes = new Uint8Array(await readFile(args[1]));
      return print(
        await client.upload(args[0], args[2] || basename(args[1]), bytes),
      );
    }
    case "download": {
      need(2);
      const file = await client.download(args[0], args[1]);
      const out = args[2] || file.name;
      await writeFile(out, file.bytes);
      return console.log(`${out} (${file.bytes.length} bytes)`);
    }
    case "rm":
      need(2);
      return print(await client.deleteFile(args[0], args[1]));
    case "task":
      need(2);
      return print(await client.submitTask(args[0], args.slice(1).join(" ")));
    case "events":
      need(1);
      return print(await client.events(args[0]));
    case "screens":
      need(1);
      return print(await client.screens(args[0]));
    case "screen-add":
      need(1);
      return print(await client.addScreen(args[0], args[1] || "1440x900"));
    case "screen-rm":
      need(2);
      return print(await client.removeScreen(args[0], Number(args[1])));
    case "apps":
      need(1);
      return print(
        (await client.apps(args[0])).map((a) => ({
          id: a.id,
          name: a.name,
          status: a.install?.status || "not installed",
        })),
      );
    case "app-install":
      need(2);
      return print(await client.installApp(args[0], args[1]));
    case "app-launch":
      need(2);
      return print(
        await client.launchApp(args[0], args[1], Number(flags.screen || 0)),
      );
    case "automations":
      need(1);
      return print(await client.automations(args[0]));
    case "automation-add": {
      need(2);
      const text = args[1].trim().startsWith("{")
        ? args[1]
        : await readFile(args[1], "utf8");
      return print(await client.createAutomation(args[0], JSON.parse(text)));
    }
    case "automation-run":
      need(1);
      return print(await client.runAutomation(args[0]));
    case "automation-runs":
      need(1);
      return print(await client.automationRuns(args[0]));
    case "fleet":
      need(1);
      return print(
        await client.fleet(args[0], {
          ...(flags.q ? { q: String(flags.q) } : {}),
          ...(flags.status ? { status: String(flags.status) } : {}),
          ...(flags.label ? { label: String(flags.label) } : {}),
        }),
      );
    case "label":
      need(1);
      return print(await client.setLabels(args[0], args.slice(1)));
    case "bulk":
      need(3);
      return print(
        await client.bulk(
          args[0],
          args[2].split(","),
          args[1] as "start" | "stop" | "add_label" | "remove_label",
          flags.label ? String(flags.label) : undefined,
        ),
      );
    case "move":
      need(2);
      return print(await client.move(args[0], args[1]));
    case "template-starters":
      return print(await client.templateStarters());
    case "templates":
      need(1);
      return print(await client.templateDefinitions(args[0]));
    case "template-publish":
      need(3);
      return print(
        await client.publishTemplate(
          args[0],
          args[1],
          JSON.parse(await readFile(args[2], "utf8")),
        ),
      );
    case "template-create":
      need(2);
      return print(
        await client.createFromTemplate(args[0], {
          name: args.slice(1).join(" "),
        }),
      );
    default:
      throw new Error(`Unknown command ${command}\n\n${HELP}`);
  }
}

main().catch((e) => {
  console.error(
    e instanceof CubicleError ? `${e.status}: ${e.message}` : e.message || e,
  );
  process.exitCode = 1;
});
