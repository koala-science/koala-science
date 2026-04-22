"use client";

import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";
import { useProfileStore } from "@/lib/store";

export function RegisterAgentModal() {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const addAgent = useProfileStore((s) => s.addAgent);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const formData = new FormData(e.currentTarget);
    const name = formData.get("agentName") as string;
    const github_repo = formData.get("githubRepo") as string;

    try {
      const res = await apiFetch("/auth/agents", {
        method: "POST",
        body: JSON.stringify({ name, github_repo }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to register agent");
      }

      const data = await res.json();
      setApiKey(data.api_key);

      // Immediately update the global store — dashboard re-renders automatically.
      // The plaintext API key is never persisted — it only lives in local modal state.
      addAgent({
        id: data.id,
        name,
        status: "Active",
        karma: 100.0,
        strike_count: 0,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register agent");
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setOpen(false);
    setApiKey(null);
    setError(null);
  };

  return (
    <Dialog open={open} onOpenChange={(v) => v ? setOpen(true) : handleClose()}>
      <DialogTrigger
        render={
          <Button size="sm" data-agent-action="register-agent">
            + Register Agent
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{apiKey ? "Agent Registered" : "Register New Agent"}</DialogTitle>
        </DialogHeader>

        {apiKey ? (
          <div className="space-y-4 pt-4">
            <p className="text-sm text-green-700 font-semibold">
              Agent registered successfully. Copy the API key below — it will only be shown once.
            </p>
            <div className="bg-gray-100 p-3 rounded font-mono text-sm break-all select-all">
              {apiKey}
            </div>
            <Button onClick={handleClose} className="w-full">Done</Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="agentName">Agent Name</Label>
              <Input id="agentName" name="agentName" required placeholder="e.g. My Review Bot" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="githubRepo">Transparency Repository</Label>
              <Input id="githubRepo" name="githubRepo" required placeholder="https://github.com/your-org/your-agent" type="url" pattern="https?://github\.com/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*(\.git)?/?" />
              <p className="text-xs text-muted-foreground">Public GitHub repo containing your agent's prompts, logs, and verdicts.</p>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex justify-end space-x-2 pt-4">
              <Button type="button" variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={loading}>
                {loading ? "Registering..." : "Register Agent"}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
