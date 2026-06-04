// Jenkinsfile
//
// Declarative Pipeline: run pytest-mrt migration safety checks.
// Add the 'Migration Safety' stage before your deploy stage.

pipeline {
    agent any

    environment {
        TEST_DATABASE_URL = credentials('test-database-url')  // Jenkins secret
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Migration Safety') {
            parallel {
                stage('Static Analysis') {
                    steps {
                        sh '''
                            python -m venv .venv
                            .venv/bin/pip install pytest-mrt --quiet
                            .venv/bin/mrt check alembic/versions/ --format json > mrt-static.json
                        '''
                        archiveArtifacts artifacts: 'mrt-static.json'
                    }
                    post {
                        failure {
                            echo 'Migration static analysis found unsafe patterns. Check mrt-static.json.'
                        }
                    }
                }

                stage('Rollback Verification') {
                    steps {
                        sh '''
                            .venv/bin/pip install pytest-mrt[postgres] --quiet
                            .venv/bin/pytest tests/test_migrations.py -v \
                                --junitxml=mrt-results.xml
                        '''
                    }
                    post {
                        always {
                            junit 'mrt-results.xml'
                        }
                    }
                }
            }
        }

        stage('Generate Report') {
            steps {
                sh '.venv/bin/mrt report alembic/versions/ --output migration_report.html'
                publishHTML([
                    allowMissing: false,
                    alwaysLinkToLastBuild: true,
                    keepAll: true,
                    reportDir: '.',
                    reportFiles: 'migration_report.html',
                    reportName: 'Migration Safety Report',
                ])
            }
        }

        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                echo 'Migrations are safe — deploying...'
                // your deploy steps here
            }
        }
    }
}
