"use client";

import { Sidebar, Toasty } from "@cloudflare/kumo";
import { CodeIcon, HouseIcon, WaveformIcon } from "@phosphor-icons/react";
import { UserAvatarDropdown } from "@/components/custom/user-avatar";
import { AuthGuard } from "@/components/custom/auth-guard";
import { ChatBreadcrumbs } from "@/components/custom/chat-breadcrumbs";
import { ChatSidebar } from "@/components/custom/chat-sidebar";
import { NotebookSidebar } from "@/components/custom/notebook-sidebar";
import { ReactNode } from "react";
import { ArrowUpRightIcon } from "@phosphor-icons/react/dist/ssr";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <Sidebar.Provider className="h-screen" peekable defaultOpen={false}>
        <Toasty>
          <Sidebar>
            <Sidebar.Header className="h-14 w-full bg-kumo-canvas">
              <Sidebar.Menu className="w-full">
                <Sidebar.MenuButton icon={WaveformIcon} className="w-full">
                  <div className="justify-between flex w-full">
                    <span>Flow</span>
                    <span>
                      <ArrowUpRightIcon className="text-kumo-subtle" />
                    </span>
                  </div>
                </Sidebar.MenuButton>
              </Sidebar.Menu>
            </Sidebar.Header>
            <Sidebar.Content className="bg-kumo-canvas">
              <Sidebar.Group>
                <Sidebar.Menu>
                  <Sidebar.MenuButton icon={HouseIcon} active>
                    Home
                  </Sidebar.MenuButton>
                </Sidebar.Menu>
              </Sidebar.Group>
              <Sidebar.Group>
                <Sidebar.GroupLabel>AI</Sidebar.GroupLabel>
                <Sidebar.Menu>
                  <ChatSidebar />
                </Sidebar.Menu>
              </Sidebar.Group>
              <NotebookSidebar />
              <Sidebar.Group>
                <Sidebar.GroupLabel>Build</Sidebar.GroupLabel>
                <Sidebar.Menu>
                  <Sidebar.MenuItem>
                    <Sidebar.Collapsible defaultOpen>
                      <Sidebar.CollapsibleTrigger
                        render={
                          <Sidebar.MenuButton icon={CodeIcon}>
                            Compute <Sidebar.MenuChevron />
                          </Sidebar.MenuButton>
                        }
                      />
                      <Sidebar.CollapsibleContent>
                        <Sidebar.MenuSub>
                          <Sidebar.MenuSubButton>
                            Containers <Sidebar.MenuBadge>Beta</Sidebar.MenuBadge>
                          </Sidebar.MenuSubButton>
                        </Sidebar.MenuSub>
                      </Sidebar.CollapsibleContent>
                    </Sidebar.Collapsible>
                  </Sidebar.MenuItem>
                </Sidebar.Menu>
              </Sidebar.Group>
            </Sidebar.Content>
            <Sidebar.Footer className="h-14 bg-kumo-canvas">
              <Sidebar.Trigger />
            </Sidebar.Footer>
          </Sidebar>
          <div className="flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-x-clip">
            <header className="flex h-14 shrink-0 items-center gap-2 border-b border-b-kumo-hairline bg-kumo-canvas/80 px-4 backdrop-blur-md">
              <Sidebar.Trigger className="flex sm:hidden" />
              <ChatBreadcrumbs />
              <UserAvatarDropdown />
            </header>
            <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-kumo-base">{children}</div>
          </div>
        </Toasty>
      </Sidebar.Provider>
    </AuthGuard>
  );
}
