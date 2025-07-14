document.addEventListener('DOMContentLoaded', function() {
    // Mobile menu toggle
    const mobileMenuToggle = document.querySelector('.mobile-menu-toggle');
    const nav = document.querySelector('nav');
    const navUl = nav ? nav.querySelector('ul') : null;
    
    if (mobileMenuToggle && navUl) {
        mobileMenuToggle.addEventListener('click', function() {
            this.classList.toggle('open');
            navUl.classList.toggle('open');
        });
    }
    
    // Close mobile menu when clicking on a link
    if (navUl) {
        navUl.querySelectorAll('li a').forEach(link => {
            link.addEventListener('click', function() {
                if (mobileMenuToggle && mobileMenuToggle.classList.contains('open')) {
                    mobileMenuToggle.classList.remove('open');
                    navUl.classList.remove('open');
                }
            });
        });
    }
    
    // Smooth scrolling for navigation links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                window.scrollTo({
                    top: target.offsetTop - 80,
                    behavior: 'smooth'
                });
            }
        });
    });

    // Header scroll effect
    const header = document.querySelector('header');
    window.addEventListener('scroll', function() {
        if (window.scrollY > 50) {
            header.style.padding = '10px 0';
            header.style.backgroundColor = 'rgba(0, 0, 0, 0.9)';
        } else {
            header.style.padding = '20px 0';
            header.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
        }
    });

    // Accordion functionality
    const accordionItems = document.querySelectorAll('.accordion-item');
    accordionItems.forEach(item => {
        const header = item.querySelector('.accordion-header');
        header.addEventListener('click', function() {
            // Close all other accordion items
            accordionItems.forEach(otherItem => {
                if (otherItem !== item && otherItem.classList.contains('active')) {
                    otherItem.classList.remove('active');
                }
            });
            
            // Toggle current accordion item
            item.classList.toggle('active');
        });
    });

    // Tab functionality
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabPanes = document.querySelectorAll('.tab-pane');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            // Remove active class from all buttons and panes
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabPanes.forEach(pane => pane.classList.remove('active'));
            
            // Add active class to current button and corresponding pane
            this.classList.add('active');
            const tabId = this.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });

    // Form submission
    const contactForm = document.getElementById('contact-form');
    if (contactForm) {
        contactForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Get form values
            const name = document.getElementById('name').value;
            const email = document.getElementById('email').value;
            const company = document.getElementById('company').value;
            const message = document.getElementById('message').value;
            
            // Here you would typically send the form data to a server
            // For demonstration, we'll just show an alert
            alert('Спасибо за ваше сообщение! Мы свяжемся с вами в ближайшее время.');
            
            // Reset form
            contactForm.reset();
        });
    }

    // Animation on scroll
    const animateOnScroll = function() {
        const elements = document.querySelectorAll('.benefit-card, .accordion-item, h2, .business-help-card, .benefits-list li, .for-all-image');
        
        elements.forEach(element => {
            const elementPosition = element.getBoundingClientRect().top;
            const windowHeight = window.innerHeight;
            
            if (elementPosition < windowHeight - 100) {
                element.classList.add('fade-in');
            }
        });
    };
    
    // Run animation check on load and scroll
    window.addEventListener('load', animateOnScroll);
    window.addEventListener('scroll', animateOnScroll);

    // Add floating animation to benefit cards
    const benefitCards = document.querySelectorAll('.benefit-card');
    benefitCards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.2}s`;
        card.classList.add('float');
    });
    
    // Add floating animation to business help cards
    const businessHelpCards = document.querySelectorAll('.business-help-card');
    businessHelpCards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.2}s`;
        card.classList.add('float');
    });
    
    // Add staggered animation to benefits list
    const benefitsList = document.querySelectorAll('.benefits-list li');
    benefitsList.forEach((item, index) => {
        item.style.animationDelay = `${index * 0.1}s`;
        item.classList.add('fade-in');
    });

    // Add pulse animation to submit button
    const submitBtn = document.querySelector('.submit-btn');
    if (submitBtn) {
        submitBtn.classList.add('pulse');
    }
});