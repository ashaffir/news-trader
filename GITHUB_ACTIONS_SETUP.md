# GitHub Actions Deployment Setup

This guide will help you set up automated deployment to your production server using GitHub Actions.

## Overview

The GitHub Actions workflow will:
1. **Run tests** when code is pushed to `main` branch
2. **Deploy automatically** if tests pass
3. **SSH into your production server** and run the deployment script
4. **Verify deployment** with health checks

## Prerequisites

### On Your Production Server

1. **Docker and Docker Compose installed**
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sh get-docker.sh
   
   # Install Docker Compose
   sudo apt-get update
   sudo apt-get install docker-compose-plugin
   ```

2. **Git repository cloned**
   ```bash
   cd /home/yourusername
   git clone https://github.com/yourusername/news-trader.git
   cd news-trader
   ```

3. **Production environment configured**
   - Create `.env` file with production settings
   - Ensure all required API keys are configured
   - Test that `docker-compose up -d` works

4. **SSH key access configured**
   - GitHub Actions will need SSH access to your server
   - We'll set this up in the next section

### On GitHub (Repository Settings)

You need to configure these **GitHub Secrets** for the deployment to work.

## Step 1: Create SSH Key Pair

On your **local machine** (not the server), create a new SSH key pair specifically for GitHub Actions:

```bash
# Generate SSH key pair
ssh-keygen -t ed25519 -C "github-actions-deployment" -f ~/.ssh/github_actions_deploy

# This creates two files:
# ~/.ssh/github_actions_deploy (private key)
# ~/.ssh/github_actions_deploy.pub (public key)
```

## Step 2: Configure SSH Access on Production Server

1. **Copy the public key to your server:**
   ```bash
   # Copy public key to clipboard
   cat ~/.ssh/github_actions_deploy.pub
   
   # SSH to your server and add it to authorized_keys
   ssh yourusername@your-server-ip
   mkdir -p ~/.ssh
   echo "your-public-key-content-here" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   chmod 700 ~/.ssh
   ```

2. **Test SSH access:**
   ```bash
   # From your local machine, test the connection
   ssh -i ~/.ssh/github_actions_deploy yourusername@your-server-ip
   ```

## Step 3: Configure GitHub Secrets

Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**

Click **"New repository secret"** for each of these:

### Required Secrets

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `PRODUCTION_HOST` | Your server's IP address or domain | `123.45.67.89` or `myserver.com` |
| `PRODUCTION_USER` | SSH username on your server | `ubuntu` or `yourusername` |
| `PRODUCTION_SSH_KEY` | Private SSH key content | Contents of `~/.ssh/github_actions_deploy` |

### Optional Secrets

| Secret Name | Description | Default Value |
|-------------|-------------|---------------|
| `PRODUCTION_PORT` | SSH port (if not 22) | `22` |
| `PRODUCTION_PATH` | Path to project on server | `/home/yourusername/news-trader` |

### How to Add Each Secret

1. **PRODUCTION_HOST**
   - Name: `PRODUCTION_HOST`
   - Secret: `your-server-ip-or-domain`

2. **PRODUCTION_USER**
   - Name: `PRODUCTION_USER`
   - Secret: `your-ssh-username`

3. **PRODUCTION_SSH_KEY**
   - Name: `PRODUCTION_SSH_KEY`
   - Secret: Copy the **entire contents** of your private key file:
   ```bash
   cat ~/.ssh/github_actions_deploy
   ```
   - Copy everything including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`

4. **PRODUCTION_PORT** (only if using non-standard SSH port)
   - Name: `PRODUCTION_PORT`
   - Secret: `2222` (or whatever port you use)

5. **PRODUCTION_PATH** (only if project is not in default location)
   - Name: `PRODUCTION_PATH`
   - Secret: `/path/to/your/news-trader`

## Step 4: Prepare Production Server

1. **Ensure project is in correct location:**
   ```bash
   # Default location (adjust PRODUCTION_PATH if different)
   cd /home/yourusername/news-trader
   
   # Verify git repository is properly set up
   git remote -v
   git status
   ```

2. **Make deployment script executable:**
   ```bash
   chmod +x deploy.sh
   ```

3. **Test deployment script manually:**
   ```bash
   # Test the deployment script
   ./deploy.sh health    # Check if services are healthy
   ./deploy.sh deploy    # Run full deployment
   ```

4. **Verify Docker access:**
   ```bash
   # Ensure your user can run Docker commands
   docker --version
   docker-compose --version
   
   # If permission denied, add user to docker group:
   sudo usermod -aG docker $USER
   # Then log out and back in
   ```

## Step 5: Test the Workflow

1. **Make a test change** and push to main branch:
   ```bash
   # Make a small change (like updating a comment)
   echo "# Test deployment" >> README.md
   git add README.md
   git commit -m "Test automated deployment"
   git push origin main
   ```

2. **Monitor the deployment:**
   - Go to your GitHub repository → **Actions** tab
   - Watch the workflow run
   - Check both "Test" and "Deploy" jobs

3. **Verify on server:**
   ```bash
   # SSH to your server and check
   cd /home/yourusername/news-trader
   docker-compose ps
   curl http://localhost:8800/health/
   ```

## Workflow Behavior

### What Triggers Deployment
- ✅ Push to `main` branch (automatic)
- ✅ Manual trigger via GitHub Actions UI
- ❌ Pull requests (tests run, but no deployment)
- ❌ Pushes to other branches

### Deployment Process
1. **Tests run first** - deployment only happens if tests pass
2. **SSH to server** using configured credentials
3. **Pull latest code** from Git repository
4. **Stop services** gracefully (brief downtime starts)
5. **Rebuild Docker images** with latest code
6. **Run database migrations** automatically
7. **Collect static files** for Django
8. **Start services** (downtime ends)
9. **Health check** to verify successful deployment
10. **Report status** in GitHub Actions log

### Expected Downtime
- **Normal deployment**: 1-3 minutes
- **First deployment or major changes**: 3-5 minutes
- **If health check fails**: Services will attempt restart

## Troubleshooting

### Common Issues

1. **SSH Permission Denied**
   ```bash
   # Verify SSH key is correctly added to server
   ssh -i ~/.ssh/github_actions_deploy yourusername@your-server-ip
   
   # Check authorized_keys permissions
   ls -la ~/.ssh/authorized_keys  # Should be 600
   ```

2. **Docker Permission Denied**
   ```bash
   # Add user to docker group
   sudo usermod -aG docker yourusername
   # Log out and back in
   ```

3. **Git Pull Fails**
   ```bash
   # Ensure git remote is set correctly
   cd /path/to/news-trader
   git remote -v
   git fetch origin  # Should work without errors
   ```

4. **Health Check Fails**
   ```bash
   # Check service status manually
   docker-compose ps
   docker-compose logs web
   curl http://localhost:8800/health/
   ```

5. **Deployment Script Fails**
   ```bash
   # Run deployment script manually to debug
   cd /path/to/news-trader
   ./deploy.sh deploy
   
   # Check specific issues
   ./deploy.sh health
   ```

### Manual Recovery

If automatic deployment fails, you can always deploy manually:

```bash
# SSH to your server
ssh yourusername@your-server-ip

# Navigate to project
cd /path/to/news-trader

# Run deployment manually
./deploy.sh deploy

# Or step by step:
git pull origin main
docker-compose down
docker-compose build --no-cache
docker-compose run --rm web python manage.py migrate
docker-compose run --rm web python manage.py collectstatic --noinput
docker-compose up -d
```

### Rolling Back

If you need to rollback a deployment:

```bash
# SSH to server
ssh yourusername@your-server-ip
cd /path/to/news-trader

# Use the rollback command
./deploy.sh rollback
```

### Monitoring Deployments

1. **GitHub Actions logs**: Check the Actions tab in your repository
2. **Server logs**: SSH to server and run `docker-compose logs -f`
3. **Health endpoint**: Visit `http://your-server:8800/health/`
4. **Dashboard**: Visit `http://your-server:8800/dashboard/`

## Security Considerations

1. **SSH Key**: The private SSH key stored in GitHub Secrets has access to your server. Keep it secure.
2. **Secrets**: Never commit secrets to your repository. Always use GitHub Secrets.
3. **Server access**: The deployment user should have minimal necessary permissions.
4. **Firewall**: Ensure only necessary ports are open on your server.

## Next Steps

After successful setup:

1. **Monitor first few deployments** to ensure they work smoothly
2. **Set up monitoring** for your production service (logs, alerts)
3. **Consider backup strategy** for your database
4. **Document any custom configuration** specific to your setup

## Support

If you encounter issues:

1. **Check GitHub Actions logs** for detailed error messages
2. **SSH to server** and run commands manually to isolate issues
3. **Review this documentation** for common troubleshooting steps
4. **Test with minimal changes** first to verify the workflow

The deployment system is designed to be robust and provide clear error messages to help with troubleshooting.
