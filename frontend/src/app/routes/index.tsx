import { createBrowserRouter } from "react-router-dom";
import ChatPage from "@/pages/chat";
import ProfilePage from "@/pages/profile";
import { TabLayout } from "@/shared/layouts/tab-layout";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <TabLayout />,
    children: [
      {
        index: true,
        element: <ChatPage />,
      },
      {
        path: "chat",
        element: <ChatPage />,
      },
      {
        path: "profile",
        element: <ProfilePage />,
      },
    ],
  },
]);
