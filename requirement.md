POST - /posts
@description Create a post
@params string authorId, string content, string communityId?
@returns Post post

GET - /posts/:postId
@description Get a single post with its comments and nested replies
@params string postId
@returns Post post, Comment[] comments

PUT - /posts/:postId
@description Update a post
@params string postId, string content
@returns Post post

DELETE - /posts/:postId
@description Delete a post
@params string postId
@returns boolean success

POST - /posts/:postId/comments
@description Create a comment on a post or a reply to another comment on that post
@params string postId, string authorId, string content, string parentCommentId?
@returns Comment comment

GET - /posts/:postId/comments
@description Get all comments for a post, including replies
@params string postId
@returns Comment[] comments

PUT - /comments/:commentId
@description Update a comment or reply
@params string commentId, string content
@returns Comment comment

GET - /course-list
@description Get the user's course planning data, including selected courses, invalid dependency courses, and all courses
@params string userId
@returns Course[] selectedCourses, Course[] invalidDependencyCourses, Course[] allCourses

POST - /course-list
@description Update the course state of the user for a single course
@params string userId, string courseId, string status
@returns Course[] selectedCourses, Course[] invalidDependencyCourses, Course[] allCourses

GET - /courses/:courseId
@description Get course information and students associated with a course
@params string courseId
@returns Course course, User[] students

POST - /auth/register
@description Register a new user account
@params string name, string email, string password
@returns User user, string token

POST - /auth/login
@description Log in a user
@params string email, string password
@returns User user, string token

POST - /auth-check
@description Validate a token and return the authenticated user
@params string token
@returns boolean valid, User user

GET - /users/:userId
@description Get a user profile including profile picture, stats, tags, and interests
@params string userId
@returns User user, string profilePictureUrl, UserStats stats, string[] tags, string[] interests

GET - /connect
@description Open the connect flow for an NFC or invite identifier
@params string id
@returns string id, boolean exists, string nextRoute

GET - /register
@description Open the registration flow for an NFC or invite identifier
@params string id
@returns string id, boolean validInvite, string nextRoute

GET - /nfc
@description Check whether an NFC identifier is already registered; if not, route to register, otherwise route to connect
@params string id
@returns string id, boolean registered, string nextRoute

POST - /chats/:chatId/messages
@description Send a message in a chat
@params string chatId, string senderId, string content
@returns Message message

GET - /chats/:chatId/messages
@description List messages in a chat
@params string chatId
@returns Message[] messages

PUT - /messages/:messageId
@description Update a previously sent message
@params string messageId, string content
@returns Message message

DELETE - /messages/:messageId
@description Delete a message
@params string messageId
@returns boolean success


SOCKET EMITTERS

message:sent
@description Emitted when a new chat message is sent
@params Message message, string chatId
@returns void emitted

message:updated
@description Emitted when a chat message is updated
@params Message message, string chatId
@returns void emitted

message:deleted
@description Emitted when a chat message is deleted
@params string messageId, string chatId
@returns void emitted