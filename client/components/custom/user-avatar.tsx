"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Dialog, DropdownMenu, Input, Text } from "@cloudflare/kumo";
import { LaptopIcon, PencilSimpleIcon, SignOutIcon, UserIcon } from "@phosphor-icons/react";
import { useTheme } from "next-themes";
import { authClient, signOut, useSession } from "@/lib/auth-client";

function initials(name: string | null | undefined, email: string | null | undefined) {
  if (name?.trim()) {
    return name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("");
  }
  return email?.[0]?.toUpperCase() ?? "?";
}

export function UserAvatarDropdown() {
  const { setTheme, theme } = useTheme();
  const { data } = useSession();
  const router = useRouter();
  const themes = ["light", "dark", "system"];

  const [profileOpen, setProfileOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const user = data?.user;

  const openProfile = () => {
    setName(user?.name ?? "");
    setProfileError(null);
    setProfileOpen(true);
  };

  const saveProfile = async () => {
    const next = name.trim();
    if (!next) {
      setProfileError("Name cannot be empty.");
      return;
    }
    setSaving(true);
    setProfileError(null);
    try {
      const { error } = await authClient.updateUser({ name: next });
      if (error) {
        setProfileError("Could not update profile. Please try again.");
      } else {
        setProfileOpen(false);
      }
    } catch {
      setProfileError("Could not update profile. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    await signOut();
    router.push("/auth");
    router.refresh();
  };

  return (
    <div className="ml-auto flex items-center">
      <DropdownMenu>
        <DropdownMenu.Trigger
          render={
            <Button
              variant="ghost"
              className="text-kumo-default"
              shape="square"
              aria-label={user ? `Account: ${user.email}` : "Account"}
            >
              {user?.image ? (
                // oxlint-disable-next-line @next/next/no-img-element
                <img
                  src={user.image}
                  alt=""
                  className="w-full h-full rounded-lg hover:brightness-95 dark:brightness-90"
                  aria-hidden
                />
              ) : user ? (
                <span
                  aria-hidden
                  className="flex h-5 w-5 items-center justify-center rounded-full bg-kumo-contrast text-[11px] font-medium text-kumo-inverse"
                >
                  {initials(user.name, user.email)}
                </span>
              ) : (
                <UserIcon aria-hidden />
              )}
            </Button>
          }
        />
        <DropdownMenu.Content>
          <div className="grid gap-1.5 px-2 py-1.5">
            <Text bold truncate>
              {user?.name ?? "Account"}
            </Text>
            {user?.email && (
              <Text variant="secondary" truncate>
                {user.email}
              </Text>
            )}
          </div>
          <DropdownMenu.Separator />
          <DropdownMenu.Sub>
            <DropdownMenu.SubTrigger icon={LaptopIcon}>Theme</DropdownMenu.SubTrigger>
            <DropdownMenu.SubContent>
              <DropdownMenu.Group>
                <DropdownMenu.RadioGroup value={theme} onValueChange={setTheme}>
                  {themes.map((themeOption) => (
                    <DropdownMenu.RadioItem
                      key={themeOption}
                      value={themeOption}
                      className="capitalize"
                    >
                      {themeOption}
                      <DropdownMenu.RadioItemIndicator />
                    </DropdownMenu.RadioItem>
                  ))}
                </DropdownMenu.RadioGroup>
              </DropdownMenu.Group>
            </DropdownMenu.SubContent>
          </DropdownMenu.Sub>
          <DropdownMenu.Item icon={PencilSimpleIcon} onClick={openProfile}>
            Profile
          </DropdownMenu.Item>
          <DropdownMenu.Separator />
          <DropdownMenu.Item icon={SignOutIcon} variant="danger" onClick={handleLogout}>
            Log out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu>

      <Dialog.Root open={profileOpen} onOpenChange={setProfileOpen}>
        <Dialog className="p-8">
          <Dialog.Title className="text-lg font-semibold">Update profile</Dialog.Title>
          <Dialog.Description className="mt-1.5 text-sm text-kumo-subtle">
            This name is shown in your workspace.
          </Dialog.Description>
          <div className="mt-4">
            <Input
              label="Name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              error={profileError ?? undefined}
            />
          </div>
          <div className="mt-8 flex justify-end gap-2">
            <Dialog.Close
              render={(props) => (
                <Button variant="secondary" {...props}>
                  Cancel
                </Button>
              )}
            />
            <Button variant="primary" loading={saving} disabled={saving} onClick={saveProfile}>
              Save changes
            </Button>
          </div>
        </Dialog>
      </Dialog.Root>
    </div>
  );
}
