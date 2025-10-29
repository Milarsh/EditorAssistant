# Snippet Front

## Tech Stack

- **Framework**: React 19
- **Architecture**: Feature-Sliced Design (FSD)
- **Build Tool**: Vite 6
- **Routing**: TanStack Router
- **State Management**: Zustand
- **Styling**: Tailwind CSS 4
- **Testing**: Vitest
- **Storybook**: For isolated UI development and testing
- **Code Quality**:
  - ESLint 9
  - Prettier
  - Husky (Git hooks)
  - Commitlint
- **Package Manager**: Yarn

## Development

### Prerequisites

- Node.js 18+
- Yarn 1.22+

### Installation

```bash
# Clone repository
git clone [repository-url]

# Install dependencies
yarn install
```

### Available Scripts

```bash
# Start development server
yarn dev

# Build for production
yarn build:prod

# Build for staging
yarn build:stage

# Build for development
yarn build:dev

# Preview production build
yarn serve

# Run tests
yarn test

# Run linter
yarn lint

# Format code
yarn format

# Check and fix code quality
yarn check
```

## Build Commands

For production build use:

```bash
yarn build:prod
```

For staging build use:

```bash
yarn build:stage
```

## CI\CD

- Раскомментируйте файл .gitlab-ci.yml, измените поля PROJECT_ALIAS and BASE_DOMAIN на требуемые.
- Напишите в команду devops о том что вам нужно задеплоить приложение.
