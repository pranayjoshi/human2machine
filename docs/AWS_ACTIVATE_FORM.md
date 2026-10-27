# AWS Activate intake form: answers ready to paste

Prepared October 27, 2026. These answers match what the public site (humans2machines.com) says and what the repository actually does. Nothing here has been submitted.

## Before you open the form

1. **Deploy the updated site** and confirm https://humans2machines.com/privacy/ loads (it returned 404 before). The site needs: About with your name, contact email, privacy page, product description, console screenshots, honest status table.
2. **LinkedIn** is set in `apps/developer-console/components/landing/LandingSections.tsx` (`FOUNDER.linkedin`). Make sure your LinkedIn profile lists H2M as your current role.
3. **Create the AWS account** on the paid plan, with root email `pranay@humans2machines.com` and a payment method, then copy the 12-digit Account ID.
4. Use **exactly the same company name, description and website** everywhere (the form, the site, LinkedIn).

## Answers

| Field | Answer |
|---|---|
| Accelerator Cohort | Pick your Harvard Foundry cohort from the list. |
| First Name | Pranay |
| Last Name | Joshi |
| Company Name | Humans2Machines (H2M) |
| Company Website | https://humans2machines.com |
| Business Email | pranay@humans2machines.com (the same address as the AWS root account) |
| AWS Account ID | Your 12-digit ID (digits only, no dashes). |
| Company Description | H2M builds a human-to-robot intent layer. It fuses speech, vision, pointing and muscle (EMG) signals into confidence-scored, machine-readable instructions that a robot can carry out behind a deterministic safety gate. We are an early-stage, bootstrapped team with a working simulator-first prototype, and we are benchmarking grounded-instruction models for robot manipulation. |
| Business Stage | Pre-seed / prototype, bootstrapped (choose the closest option; do not select "incorporated" or "funded"). |
| Where do you learn about tech? | arXiv, X, Hugging Face papers and GitHub. Edit to match your real habits. |
| AI Profile | The option closest to "builds or fine-tunes AI models". |
| GenAI Models | Claude (development), Qwen3-VL and Xiaomi-Robotics-1 (open vision-language and robot-action models), π0.5, YOLOE (detection), Parakeet (speech recognition). |
| Fine-tuning? | Yes: LoRA and partial fine-tuning of vision-language-action models on robot demonstration data. |
| AI Agents Framework/Tooling | None or custom. |
| Agent Technical Challenges | Grounding instructions in images, latency, reliable step-by-step execution, evaluation cost. |
| Which AI Coding Tools Do You Use? | Claude Code. |
| How do AI tools influence your stack decisions? | We choose models by benchmark performance, license (open weights we can ship) and cost. |
| Primary Cloud | AWS (new account; planned primary cloud). |
| Why this cloud? | NVIDIA documents Isaac Sim, the robotics simulator we need, on AWS EC2, and L40S GPUs fit both simulation and fine-tuning. Startup credits make it viable. |
| Front-End Hosting Provider | Your current host (the landing site is a static Next.js export). |
| Back-End Hosting Provider | Local Python services today; AWS EC2 for GPU jobs. |
| Database Provider | None yet (local Parquet files). |
| Inference Provider | Self-hosted on GPU instances, with Amazon Bedrock for development. |
| Most important factor in inference provider | Cost and control of open-weights models. |
| GPUs Used / Needed | Needed: L40S or L4 (RT-core GPUs for Isaac Sim) and A100/H100-class GPUs for training. |
| Primary GPU provider | None yet. AWS is planned. |
| Immediate AI/ML needs | Fine-tune a robot manipulation model, run Isaac Sim evaluation, and use a vision-language model to relabel training data. |
| Assistance preferred | GPU quota increases (G and VT, and P instances), Isaac Sim on EC2 architecture advice, Bedrock guidance. |

## Rules of thumb

- Be truthful about stage and entity status. Do not claim incorporation, funding or an existing AWS footprint.
- Submit once. If rejected, reply to the rejection email, then use the Activate contact form, and ask your Foundry contact to escalate.
- After the code arrives (check spam), redeem it in the AWS Billing console, then request GPU quota the same day.
