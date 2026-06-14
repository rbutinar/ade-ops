# Welcome email — framework skeleton

Template for inviting a new operator onto an ade-ops distribution. The
`ONBOARDING.md` of each distribution is the canonical technical reference;
this email sits **above** it, calibrating expectations and gating readiness
before the operator opens the tech doc.

## When to use this template

- A team-member or stakeholder asks for the setup
- A non-developer (PM, manager, analyst) needs visibility into the framework
- A new project is spinning up and the team needs to be brought in

Send the email **before** sharing the ONBOARDING.md link, not instead of it.
The email's job is to surface the prerequisites that aren't in `ONBOARDING.md`
because they live outside the repo (Claude license, admin rights on the
workstation, identity setup on the client tenant, time budget).

## Variables to fill per distribution

Each distribution that adopts this template creates its own instance under
`distributions/{client}/templates/welcome-email.md` with these placeholders
resolved:

| Placeholder | Meaning | Example |
|---|---|---|
| `{{recipient_name}}` | Recipient first name | "Anna" |
| `{{recipient_role}}` | What role they will play | "team-member operativo" / "PM read-only visibility" |
| `{{distribution_name}}` | The distribution they will join | "Example Distribution" |
| `{{claude_license_info}}` | How they get a Claude Code license | "License is paid by your organization — open a ticket on …" |
| `{{prereq_workstation}}` | Workstation prerequisites | "Windows 10/11 + admin rights + ~5 GB free" |
| `{{prereq_identity}}` | Identity setup on the client tenant | "Guest UPN on client tenant — request from …" |
| `{{time_estimate}}` | Realistic onboarding time | "~2 hours focused, can be split across 2 days" |
| `{{onboarding_link}}` | Pointer to ONBOARDING.md | "[ONBOARDING.md](…)" |
| `{{escalation_contact}}` | Who to ping if stuck | "Roberto Butinar (<maintainer-email>)" |
| `{{first_touchpoint}}` | What happens after setup | "30-min walkthrough call after first successful preflight" |

## Skeleton

```markdown
**Subject**: Welcome to {{distribution_name}} — ade-ops onboarding info

Ciao {{recipient_name}},

ti sto attivando come {{recipient_role}} su {{distribution_name}}, un
framework operativo basato su Claude Code per la gestione del nostro
ambiente analitico. Prima di mandarti la guida tecnica vera e propria,
ecco cosa serve sapere — il setup è semplice ma richiede alcune cose
amministrative che non sono nel repo.

## Cosa è ade-ops in 2 righe

È una "console operativa" da terminale per fare pull/push/diff/status
verso Databricks e Fabric in modo sicuro e auditabile. NON è una
dashboard read-only; ogni azione è esplicita e va confermata.

## Prerequisiti prima di partire

1. **Licenza Claude Code** — {{claude_license_info}}
2. **Workstation** — {{prereq_workstation}}
3. **Identità sul tenant cliente** — {{prereq_identity}}
4. **Tempo da prevedere** — {{time_estimate}}. Non è un setup di 10 min,
   ma neanche di una giornata intera.

## Readiness checklist (rispondimi prima di partire)

- [ ] Ho (o sto ottenendo) la licenza Claude Code
- [ ] Ho admin rights sul mio PC
- [ ] Ho l'identità sul tenant cliente (o so come ottenerla)
- [ ] Ho ~{{time_estimate}} prenotati nel calendario

Se una qualsiasi di queste è "no", dimmelo: vediamo cosa serve sbloccare
prima di farti perdere tempo sul setup.

## Cosa succede dopo

Quando i prereq sono OK, ti mando il link a {{onboarding_link}} e seguiamo
la guida tecnica passo passo. Tipicamente è auto-esplicativa, ma se ti
blocchi pingami a {{escalation_contact}}.

{{first_touchpoint}}

A presto,
Roberto
```

## Variants

The skeleton above assumes a team-member operativo. Two variants are
worth carrying as siblings under `distributions/{client}/templates/`
when the case arises:

- `welcome-email-pm.md` — read-only visibility role (PM, sponsor): tone
  more managerial, less technical, expectations about what the framework
  is and isn't ("not a dashboard, requires Claude license too if you want
  to use it directly").
- `welcome-email-tester.md` — short-term tester / pilot user: emphasis
  on "we want your friction findings", point at `/ops-feedback` flow.

Both are derivations of the same skeleton — same prereq structure, different
tone and emphasis. Create them on-demand the first time a real case arises;
don't pre-emptively template every persona.

## Maintenance

Update the placeholder list above when distributions start needing fields
the skeleton doesn't cover (e.g. a new tenant-specific prereq). Keep the
list minimal — placeholders that show up in only one distribution don't
belong here; they live in that distribution's instance file directly.
